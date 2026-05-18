import os, re, requests
from fastapi import FastAPI, Request
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from groq import Groq
from database import *

app = FastAPI()
scheduler = BackgroundScheduler(timezone=pytz.timezone('Africa/Lagos'))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
user_modes = {}

@app.on_event("startup")
async def startup():
    init_db(); scheduler.start()

def send_whatsapp(to, msg):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product":"whatsapp","to":to,"text":{"body":msg}})

def send_menu(to):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product":"whatsapp","to":to,"type":"interactive",
            "interactive":{"type":"button","body":{"text":"MarketBrain - Choose"},
                           "action":{"buttons":[
                               {"type":"reply","reply":{"id":"sale","title":"💰 Sale"}},
                               {"type":"reply","reply":{"id":"restock","title":"📦 Stock"}},
                               {"type":"reply","reply":{"id":"expense","title":"💸 Expense"}},
                               {"type":"reply","reply":{"id":"reports","title":"📊 Reports"}}
                           ]}}}
    requests.post(url, headers=headers, json=data)

def send_report_menu(to):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product":"whatsapp","to":to,"type":"interactive",
            "interactive":{"type":"list","body":{"text":"Pick report"},
                           "action":{"button":"View","sections":[{
                               "title":"Reports","rows":[
                                   {"id":"today","title":"Today"},
                                   {"id":"week","title":"This Week"},
                                   {"id":"stock","title":"Inventory"},
                                   {"id":"sales","title":"Sales History"},
                                   {"id":"profit","title":"Profit/Loss"}
                               ]}]}}}
    requests.post(url, headers=headers, json=data)

def transcribe_audio(media_id):
    try:
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        meta = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers=headers).json()
        url = meta.get('url')
        audio_bytes = requests.get(url, headers=headers).content
        resp = groq_client.audio.transcriptions.create(
            file=("voice.ogg", audio_bytes),
            model="whisper-large-v3",
            language="en",
            temperature=0
        )
        return resp.text
    except Exception as e:
        print("Transcribe error:", e)
        return ""

def extract_amount(t):
    m=re.search(r'(\d+)\s*(k|thousand)?',t); return int(m.group(1))*(1000 if m.group(2) else 1) if m else 0

def process_message(uid, text, mode):
    tl=text.lower(); user=get_user(uid)
    lang = user['language'] if user and user['language'] else 'en'
    def t(p,e): return p if lang=='pidgin' else e

    if 'reset' in tl:
        conn=get_conn();c=conn.cursor()
        for tbl in ['users','sales','expenses','inventory']: c.execute(f"DELETE FROM {tbl} WHERE user_id=%s",(uid,))
        conn.commit();conn.close();create_user(uid); return t("Reset done! Wetin be your business name?","Reset done! What's your business name?")

    if not user: create_user(uid); return "Welcome! What's your business name?"
    if not user['business_name']: update_business_name(uid,text.title()); return t(f"Nice {text.title()}! Pidgin or English?", f"Nice {text.title()}! Reply Pidgin or English")
    if not user['language']:
        update_language(uid,'pidgin' if 'pidgin' in tl else 'en')
        send_menu(uid)
        return t("You set! Tap button below.","You're all set! Tap a button below.")

    if re.match(r'\d{4}-\d{2}', tl):
        d=tl; conn=get_conn();c=conn.cursor(); c.execute("SELECT COALESCE(SUM(amount),0) FROM sales WHERE user_id=%s AND DATE(timestamp)=%s",(uid,d)); s=c.fetchone()[0]; conn.close(); return f"Sales {d}: ₦{s:,}"

    if mode=='restock' or 'bought' in tl or 'buy' in tl:
        nums=re.findall(r'(\d+)\s*(k|thousand)?',tl)
        if len(nums)>=2 and ('each' in tl or 'x' in tl):
            q=int(nums[0][0]); p=int(nums[1][0])*(1000 if nums[1][1] else 1); a=q*p
            prod=re.search(r'\d+\s+(\w+)',tl); prod=prod.group(1) if prod else 'item'
            add_stock(uid,prod,q,p); save_expense(uid,a,text,'restock')
            return t(f"Added {q} {prod}. Now: {dict(get_stock(uid)).get(prod,0)}", f"Added {q} {prod}. Stock: {dict(get_stock(uid)).get(prod,0)}")

    if mode=='sale' or 'sold' in tl or 'sell' in tl:
        nums=re.findall(r'(\d+)\s*(k|thousand)?',tl); q,p=1,0
        if len(nums)>=2 and ('each' in tl or 'x' in tl): q=int(nums[0][0]); p=int(nums[1][0])*(1000 if nums[1][1] else 1)
        elif nums: p=int(nums[0][0])*(1000 if nums[0][1] else 1)
        a=q*p; prod=re.search(r'\d+\s+(\w+)',tl); prod=prod.group(1) if prod else 'item'
        pay='transfer' if 'transfer' in tl else 'pos' if 'pos' in tl else 'cash'
        if a>0: save_sale(uid,a,prod,q,pay); return t(f"Sold {q} {prod} ₦{a:,}. Remain: {dict(get_stock(uid)).get(prod,0)}", f"Sold {q} {prod} for ₦{a:,}. Left: {dict(get_stock(uid)).get(prod,0)}")

    if mode=='expense' or (re.search(r'\d',tl) and 'sold' not in tl):
        a=extract_amount(tl)
        if a>0: save_expense(uid,a,text,'expense'); return t(f"Expense ₦{a:,} saved", f"Expense ₦{a:,} saved")

    return t("Use menu buttons","Use the menu buttons")

@app.get("/webhook")
async def verify(r:Request):
    p=dict(r.query_params); return int(p.get("hub.challenge")) if p.get("hub.verify_token")==VERIFY_TOKEN else "fail"

@app.post("/webhook")
async def webhook(r:Request):
    data=await r.json()
    try:
        msg=data['entry'][0]['changes'][0]['value']['messages'][0]; uid=msg['from']
        user=get_user(uid); lang=user['language'] if user and user['language'] else 'en'

        if msg.get('type')=='audio':
            send_whatsapp(uid, "🎤 I dey listen..." if lang=='pidgin' else "🎤 Listening...")
            text = transcribe_audio(msg['audio']['id'])
            if text:
                send_whatsapp(uid, f"You talk: '{text}'" if lang=='pidgin' else f"You said: '{text}'")
                resp = process_message(uid, text, user_modes.get(uid))
                send_whatsapp(uid, resp)
            else:
                send_whatsapp(uid, "I no hear am, try again" if lang=='pidgin' else "Didn't catch that, try again")
            send_menu(uid); return {"status":"ok"}

        if msg.get('type')=='interactive':
            bid=msg['interactive'].get('button_reply',{}).get('id') or msg['interactive'].get('list_reply',{}).get('id')
            user_modes[uid]=bid
            if bid in ['sale','restock','expense']: send_whatsapp(uid, "Send details or voice note" if lang=='en' else "Send details or voice")
            elif bid=='reports': send_report_menu(uid)
            elif bid=='today': s=get_period_sales(uid,'today'); r=get_period_expenses(uid,'today','restock'); e=get_period_expenses(uid,'today','expense'); send_whatsapp(uid,f"TODAY\nSales ₦{s:,}\nProfit ₦{s-r-e:,}")
            elif bid=='week': s=get_period_sales(uid,'week'); send_whatsapp(uid,f"Week: ₦{s:,}")
            elif bid=='stock': st=get_stock(uid); txt="\n".join([f"{p}: {q}" for p,q in st]) if st else "Empty"; send_whatsapp(uid,f"Stock:\n{txt}")
            elif bid=='sales': conn=get_conn();c=conn.cursor();c.execute("SELECT product,quantity,amount FROM sales WHERE user_id=%s ORDER BY timestamp DESC LIMIT 5",(uid,)); rows=c.fetchall();conn.close(); txt="\n".join([f"{q}x {p} - ₦{a:,}" for p,q,a in rows]) or "None"; send_whatsapp(uid,f"Last:\n{txt}")
            elif bid=='profit': s=get_period_sales(uid,'week'); r=get_period_expenses(uid,'week','restock'); send_whatsapp(uid,f"Profit: ₦{s-r:,}")
            return {"status":"ok"}

        if msg.get('type')=='text':
            text=msg['text']['body']
            if text.lower() in ['hi','menu']: send_menu(uid)
            else: resp=process_message(uid,text,user_modes.get(uid)); send_whatsapp(uid,resp);
            if 'business name' not in resp.lower() and 'pidgin or english' not in resp.lower(): send_menu(uid)
    except Exception as e: print("Error:",e)
    return {"status":"ok"}
