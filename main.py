import os, re, requests, traceback
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
    r = requests.post(url, headers=headers, json={"messaging_product":"whatsapp","to":to,"text":{"body":msg}})
    print(f"SEND {r.status_code}")

def send_menu(to):
    send_whatsapp(to, "MarketBrain:\n1 💰 Sale\n2 📦 Stock\n3 💸 Expense\n4 📊 Reports\n\nReply number")

def transcribe_audio(media_id):
    try:
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        meta = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers=headers).json()
        audio = requests.get(meta['url'], headers=headers).content
        resp = groq_client.audio.transcriptions.create(file=("voice.ogg", audio), model="whisper-large-v3")
        return resp.text
    except Exception as e:
        print("Transcribe fail:", e); return ""

def extract_amount(t):
    m=re.search(r'(\d+)\s*(k|thousand)?',t); return int(m.group(1))*(1000 if m.group(2) else 1) if m else 0

def process_message(uid, text, mode):
    user=get_user(uid); tl=text.lower()
    if 'reset' in tl:
        conn=get_conn();c=conn.cursor()
        for tbl in ['users','sales','expenses','inventory']: c.execute(f"DELETE FROM {tbl} WHERE user_id=%s",(uid,))
        conn.commit();conn.close();create_user(uid); return "RESET"
    if not user: create_user(uid); return "Welcome! Business name?"
    if not user['business_name']: update_business_name(uid,text.title()); return "__ASK_LANG__"
    if not user['language']: update_language(uid,'pidgin' if 'pidgin' in tl else 'en'); return "__SHOW_MENU__"

    lang = user['language']
    if mode=='2' or mode=='restock' or 'bought' in tl:
        nums=re.findall(r'(\d+)',tl)
        if len(nums)>=2: q,p=int(nums[0]),int(nums[1])*1000; add_stock(uid,'item',q,p); save_expense(uid,q*p,text,'restock'); return f"Added {q} items"
    if mode=='1' or mode=='sale' or 'sold' in tl:
        nums=re.findall(r'(\d+)',tl); a=int(nums[0])*1000 if nums else 0
        if a: save_sale(uid,a,'item',1,'cash'); return f"Sale ₦{a:,} saved"
    if mode=='3' or 'expense' in tl:
        a=extract_amount(tl); save_expense(uid,a,text,'expense'); return f"Expense ₦{a:,}"
    return "Saved"

@app.get("/webhook")
async def verify(r:Request):
    p=dict(r.query_params); return int(p.get("hub.challenge")) if p.get("hub.verify_token")==VERIFY_TOKEN else "fail"

@app.post("/webhook")
async def webhook(r:Request):
    try:
        data=await r.json()
        value = data['entry'][0]['changes'][0]['value']
        # SKIP status updates
        if 'messages' not in value: return {"status":"ok"}

        msg=value['messages'][0]; uid=msg['from']

        if msg.get('type')=='audio':
            send_whatsapp(uid, "🎤 Listening...")
            txt = transcribe_audio(msg['audio']['id'])
            if txt:
                send_whatsapp(uid, f"You said: {txt}")
                resp = process_message(uid, txt, user_modes.get(uid))
                send_whatsapp(uid, resp)
            else: send_whatsapp(uid, "Try again")
            send_menu(uid); return {"status":"ok"}

        if msg.get('type')=='text':
            text=msg['text']['body'].strip()
            # menu numbers
            if text in ['1','2','3','4']: user_modes[uid]=text; send_whatsapp(uid, f"Mode {text}. Send details or voice"); return {"status":"ok"}
            if text.lower() in ['hi','menu']: send_menu(uid); return {"status":"ok"}

            resp = process_message(uid,text,user_modes.get(uid))
            if resp=="RESET": send_whatsapp(uid, "Reset! Business name?")
            elif resp=="__ASK_LANG__": send_whatsapp(uid, "Reply: Pidgin or English")
            elif resp=="__SHOW_MENU__": send_whatsapp(uid, "You're set!"); send_menu(uid)
            else: send_whatsapp(uid, resp); send_menu(uid)
    except Exception as e: print("ERR",e); traceback.print_exc()
    return {"status":"ok"}
