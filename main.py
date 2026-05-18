import os, re, requests, traceback
from fastapi import FastAPI, Request
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from groq import Groq
from database import *

app = FastAPI()
scheduler = BackgroundScheduler(timezone=pytz.timezone('Africa/Lagos'))
print("Starting MarketBrain...")
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
user_modes = {}

@app.on_event("startup")
async def startup():
    init_db(); scheduler.start(); print("DB ready")

def send_whatsapp(to, msg):
    try:
        url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
        r = requests.post(url, headers=headers, json={"messaging_product":"whatsapp","to":to,"text":{"body":msg}})
        print(f"SEND to {to}: {msg[:30]}... status {r.status_code}")
    except Exception as e: print("Send error:", e)

def send_menu(to):
    try:
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
        r = requests.post(url, headers=headers, json=data)
        print(f"MENU sent to {to}, status {r.status_code}, resp {r.text[:100]}")
    except Exception as e: print("Menu error:", e)

def transcribe_audio(media_id):
    try:
        print(f"Transcribing {media_id}")
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        meta = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers=headers).json()
        print("Meta:", meta)
        audio = requests.get(meta['url'], headers=headers).content
        print(f"Audio size {len(audio)} bytes")
        resp = groq_client.audio.transcriptions.create(file=("voice.ogg", audio), model="whisper-large-v3")
        print("Transcript:", resp.text)
        return resp.text
    except Exception as e:
        print("TRANSCRIBE FAIL:", e); traceback.print_exc(); return ""

def process_message(uid, text, mode):
    tl=text.lower(); user=get_user(uid)
    print(f"Processing {uid}: '{text}' mode={mode}")
    if 'reset' in tl:
        conn=get_conn();c=conn.cursor()
        for t in ['users','sales','expenses','inventory']: c.execute(f"DELETE FROM {t} WHERE user_id=%s",(uid,))
        conn.commit();conn.close();create_user(uid); return "RESET"
    if not user: create_user(uid); return "Welcome! Business name?"
    if not user['business_name']: update_business_name(uid,text.title()); return "__ASK_LANG__"
    if not user['language']: update_language(uid,'pidgin' if 'pidgin' in tl else 'en'); return "__SHOW_MENU__"
    # simple handlers
    if 'bought' in tl or mode=='restock': return "Restock saved"
    if 'sold' in tl or mode=='sale': return "Sale saved"
    return "Got it"

@app.get("/webhook")
async def verify(r:Request):
    p=dict(r.query_params); return int(p.get("hub.challenge")) if p.get("hub.verify_token")==VERIFY_TOKEN else "fail"

@app.post("/webhook")
async def webhook(r:Request):
    try:
        data=await r.json(); print("WEBHOOK:", str(data)[:200])
        msg=data['entry'][0]['changes'][0]['value']['messages'][0]; uid=msg['from']
        print(f"Msg type {msg.get('type')} from {uid}")

        if msg.get('type')=='audio':
            send_whatsapp(uid, "🎤 Listening...")
            txt = transcribe_audio(msg['audio']['id'])
            send_whatsapp(uid, f"Heard: {txt}" if txt else "No audio")
            send_menu(uid); return {"status":"ok"}

        if msg.get('type')=='interactive':
            bid = msg['interactive'].get('button_reply',{}).get('id')
            user_modes[uid]=bid; send_whatsapp(uid, f"Mode {bid}"); return {"status":"ok"}

        if msg.get('type')=='text':
            text=msg['text']['body']
            if text.lower() in ['hi','menu']: send_menu(uid); return {"status":"ok"}
            resp = process_message(uid,text,user_modes.get(uid))
            print(f"Resp: {resp}")
            if resp=="__ASK_LANG__": send_whatsapp(uid, "Pidgin or English?")
            elif resp=="__SHOW_MENU__": send_whatsapp(uid, "Setup done!"); send_menu(uid)
            elif resp=="RESET": send_whatsapp(uid, "Reset done. Business name?");
            else: send_whatsapp(uid, resp); send_menu(uid)
    except Exception as e: print("WEBHOOK ERROR:", e); traceback.print_exc()
    return {"status":"ok"}
