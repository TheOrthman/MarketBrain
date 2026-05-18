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
        audio_bytes = requests.get(meta['url'], headers=headers).content
        resp = groq_client.audio.transcriptions.create(file=("voice.ogg", audio_bytes), model="whisper-large-v3")
        return resp.text
    except Exception as e:
        print("Transcribe:", e); return ""

def extract_amount(t):
    m=re.search(r'(\d+)\s*(k|thousand)?',t); return int(m.group(1))*(1000 if m.group(2) else 1) if m else 0

def process_message(uid, text, mode):
    tl=text.lower(); user=get_user(uid)
    lang = user['language'] if user and user['language'] else 'en'
    def t(p,e): return p if lang=='pidgin' else e

    if 'reset' in tl:
        conn=get_conn();c=conn.cursor()
        for tbl in ['users','sales','expenses','inventory']: c.execute(f"DELETE FROM {tbl} WHERE user_id=%s",(uid,))
        conn.commit();conn.close();create_user(uid); return t("Reset! Business name?","Reset done! What's your business name?")

    if not user: create_user(uid); return "Welcome! What's your business name?"
    if not user['business_name']: update_business_name(uid,text.title()); return "__ASK_LANG__"
    if not user['language']: update_language(uid,'pidgin' if 'pidgin' in tl else 'en'); return "__SHOW_MENU__"

    if mode=='restock' or 'bought' in tl:
        nums=re.findall(r'(\d+)\s*(k|thousand)?',tl)
        if len(nums)>=2:
            q=int(nums[0][0]); p=int(nums[1][0])*(1000 if nums[1][1] else 1)
            prod=re.search(r'\d+\s+(\w+)',tl); prod=prod.group(1) if prod else 'item'
            add_stock(uid,prod,q,p); save_expense(uid,q*p,text,'restock')
            return t(f"Added {q} {prod}","Added {q} {prod}".format(q=q,prod=prod))

    if mode=='sale' or 'sold' in tl:
        nums=re.findall(r'(\d+)\s*(k|thousand)?',tl); q,p=1,0
        if len(nums)>=2: q=int(nums[0][0]); p=int(nums[1][0])*(1000 if nums[1][1] else 1)
        elif nums: p=int(nums[0][0])*(1000 if nums[0][1] else 1)
        a=q*p; prod=re.search(r'\d+\s+(\w+)',tl); prod=prod.group(1) if prod else 'item'
        if a>0: save_sale(uid,a,prod,q,'cash'); return t(f"Sold {q} {prod} ₦{a:,}","Sold {q} {prod} for ₦{a:,}".format(q=q,prod=prod,a=a))

    if mode=='expense' or (re.search(r'\d',tl) and 'sold' not in tl):
        a=extract_amount(tl)
        if a>0: save_expense(uid,a,text,'expense'); return f"Expense ₦{a:,}"

    return t("Use buttons","Use menu")

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
            send_menu(uid); return {"status":"ok"}

        if msg.get('type')=='interactive':
            bid=msg['interactive'].get('button_reply',{}).get('id') or msg['interactive'].get('list_reply',{}).get('id')
            user_modes[uid]=bid
            if bid in ['sale','restock','expense']: send_whatsapp(uid, "Send text or voice" if lang=='en' else "Send text or voice")
            elif bid=='reports': send_report_menu(uid)
            elif bid=='today': s=get_period_sales(uid,'today'); send_whatsapp(uid,f"Today ₦{s:,}")
            elif bid=='stock': st=get_stock(uid); txt="\n".join([f"{p}:{q}" for p,q in st]) or "Empty"; send_whatsapp(uid,txt)
            return {"status":"ok"}

        if msg.get('type')=='text':
            text=msg['text']['body']
            if text.lower() in ['hi','menu']: send_menu(uid); return {"status":"ok"}
            resp = process_message(uid,text,user_modes.get(uid))
            if resp=="__ASK_LANG__":
                send_whatsapp(uid, f"Nice {text.title()}! Reply Pidgin or English")
            elif resp=="__SHOW_MENU__":
                send_whatsapp(uid, "You're set!" if lang=='en' else "You set!")
                send_menu(uid)
            else:
                send_whatsapp(uid, resp); send_menu(uid)
    except Exception as e: print(e)
    return {"status":"ok"}
