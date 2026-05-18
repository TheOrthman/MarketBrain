import os, re, requests
from fastapi import FastAPI, Request
from datetime import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from groq import Groq
from database import *

app = FastAPI()
scheduler = BackgroundScheduler(timezone=pytz.timezone('Africa/Lagos'))
GROQ_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None

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
        # get media url
        url = f"https://graph.facebook.com/v19.0/{media_id}"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        media_url = requests.get(url, headers=headers).json().get('url')
        # download
        audio = requests.get(media_url, headers=headers).content
        with open('/tmp/voice.ogg','wb') as f: f.write(audio)
        # transcribe
        with open('/tmp/voice.ogg','rb') as f:
            txt = groq_client.audio.transcriptions.create(
                file=f, model="whisper-large-v3", language="en"
            )
        return str(txt)
    except Exception as e:
        print("Transcribe error:", e)
        return ""

def extract_amount(t):
    m=re.search(r'(\d+)\s*(k|thousand)?',t); return int(m.group(1))*(1000 if m.group(2) else 1) if m else 0

def process_message(uid, text, mode):
    tl=text.lower(); user=get_user(uid)
    if 'reset' in tl:
        conn=get_conn();c=conn.cursor()
        for t in ['users','sales','expenses','inventory']: c.execute(f"DELETE FROM {t} WHERE user_id=%s",(uid,))
        conn.commit();conn.close();create_user(uid); return "Reset done! What's your business name?"
    if not user: create_user(uid); return "Welcome! What's your business name?"
    if not user['business_name']: update_business_name(uid,text.title()); return f"Nice {text.title()}! Pidgin or English?"
    if not user['language']: update_language(uid,'pidgin' if 'pidgin' in tl else 'en'); return "Ready! Use menu."
    if re.match(r'\d{4}-\d{2}-\d{2}', tl):
        d=tl; conn=get_conn();c=conn.cursor(); c.execute("SELECT COALESCE(SUM(amount),0) FROM sales WHERE user_id=%s AND DATE(timestamp)=%s",(uid,d)); s=c.fetchone()[0]; conn.close(); return f"Sales {d}: ₦{s:,}"
    if mode=='restock' or 'bought' in tl:
        nums=re.findall(r'(\d+)\s*(k|thousand)?',tl)
        if len(nums)>=2 and ('each' in tl or 'x' in tl):
            q=int(nums[0][0]); p=int(nums[1][0])*(1000 if nums[1][1] else 1); a=q*p
            prod=re.search(r'\d+\s+(\w+)',tl); prod=prod.group(1) if prod else 'item'
            add_stock(uid,prod,q,p); save_expense(uid,a,text,'restock')
            return f"Added {q} {prod}. Now: {dict(get_stock(uid)).get(prod,0)}"
    if mode=='sale' or 'sold' in tl:
        nums=re.findall(r'(\d+)\s*(k|thousand)?',tl); q,p=1,0
        if len(nums)>=2 and ('each' in tl or 'x' in tl): q=int(nums[0][0]); p=int(nums[1][0])*(1000 if nums[1][1] else 1)
        elif nums: p=int(nums[0][0])*(1000 if nums[0][1] else 1)
        a=q*p; prod=re.search(r'\d+\s+(\w+)',tl); prod=prod.group(1) if prod else 'item'
        pay='transfer' if 'transfer' in tl else 'pos' if 'pos' in tl else 'cash'
        if a>0: save_sale(uid,a,prod,q,pay); return f"Sold {q} {prod} ₦{a:,}. Left: {dict(get_stock(uid)).get(prod,0)}"
    if mode=='expense' or (re.search(r'\d',tl) and 'sold' not in tl):
        a=extract_amount(tl)
        if a>0: save_expense(uid,a,text,'expense'); return f"Expense ₦{a:,} saved."
    return "Use menu."

@app.get("/webhook")
async def verify(r:Request):
    p=dict(r.query_params); return int(p.get("hub.challenge")) if p.get("hub.verify_token")==VERIFY_TOKEN else "fail"

@app.post("/webhook")
async def webhook(r:Request):
    data=await r.json()
    try:
        msg=data['entry'][0]['changes'][0]['value']['messages'][0]; uid=msg['from']

        # VOICE NOTE HANDLER
        if msg.get('type')=='audio':
            send_whatsapp(uid, "🎤 I dey listen...")
            media_id = msg['audio']['id']
            text = transcribe_audio(media_id)
            if text:
                send_whatsapp(uid, f"You talk: '{text}'")
                resp = process_message(uid, text, user_modes.get(uid))
                send_whatsapp(uid, resp)
            else:
                send_whatsapp(uid, "I no hear am, try again")
            send_menu(uid)
            return {"status":"ok"}

        if msg.get('type')=='interactive':
            bid=msg['interactive'].get('button_reply',{}).get('id') or msg['interactive'].get('list_reply',{}).get('id')
            user_modes[uid]=bid
            if bid in ['sale','restock','expense']: send_whatsapp(uid,f"Send {bid} details (or voice note)")
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
            else: resp=process_message(uid,text,user_modes.get(uid)); send_whatsapp(uid,resp); send_menu(uid)
    except Exception as e: print("Error:",e)
    return {"status":"ok"}
