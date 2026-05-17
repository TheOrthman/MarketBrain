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
LAGOS = pytz.timezone('Africa/Lagos')

user_modes = {}

@app.on_event("startup")
async def startup():
    init_db()
    scheduler.start()

def send_whatsapp(to, message):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages" # FIXED
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "text": {"body": message}}
    requests.post(url, headers=headers, json=data)

def send_menu(to):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages" # FIXED
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {
        "messaging_product": "whatsapp", "to": to, "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "MarketBrain - Wetin you wan do?"},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": "sale", "title": "💰 Record Sale"}},
                {"type": "reply", "reply": {"id": "restock", "title": "📦 Add Stock"}},
                {"type": "reply", "reply": {"id": "expense", "title": "💸 Expense"}},
            ]}
        }
    }
    requests.post(url, headers=headers, json=data)

def send_report_menu(to):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages" # FIXED
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {
        "messaging_product": "whatsapp", "to": to, "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "Reports"},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": "stock", "title": "📦 Stock Left"}},
                {"type": "reply", "reply": {"id": "today", "title": "📊 Today"}},
                {"type": "reply", "reply": {"id": "profit", "title": "💵 Profit"}},
            ]}
        }
    }
    requests.post(url, headers=headers, json=data)

def extract_amount(text):
    m = re.search(r'(\d+)\s*(k|thousand)?', text)
    return int(m.group(1)) * (1000 if m.group(2) else 1) if m else 0

def classify_expense(desc):
    if not groq_client: return 'expense'
    try:
        resp = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role":"user","content":f"Classify '{desc}' as: restock,packaging,transport,delivery,fuel,rent,data,marketing,feeding,other. One word."}],
            max_tokens=5, temperature=0
        )
        cat = resp.choices[0].message.content.strip().lower()
        return cat if cat in ['restock','packaging','transport','delivery','fuel','rent','data','marketing','feeding'] else 'expense'
    except: return 'expense'

def process_message(uid, text, mode=None):
    tl = text.lower(); user = get_user(uid)

    # RESET - NEW
    if 'reset' in tl:
        conn = get_conn(); c = conn.cursor()
        for t in ['users','sales','expenses','inventory']:
            c.execute(f"DELETE FROM {t} WHERE user_id=%s", (uid,))
        conn.commit(); conn.close()
        create_user(uid)
        return "Reset done! Welcome to MarketBrain! What's your business name?"

    if not user: create_user(uid); return "Welcome! What's your business name?"
    if not user['business_name']: update_business_name(uid, text.title()); return f"Nice {text.title()}! Pidgin or English?"
    if not user['language']: update_language(uid, 'pidgin' if 'pidgin' in tl else 'en'); return "Ready! Tap menu or type."

    # RESTOCK
    if mode=='restock' or any(k in tl for k in ['bought','restock','stock','buy']):
        nums = re.findall(r'(\d+)\s*(k|thousand)?', tl)
        if len(nums)>=2 and ('each' in tl or 'x' in tl):
            qty = int(nums[0][0]); price = int(nums[1][0])*(1000 if nums[1][1] else 1)
            amount = qty*price
            m = re.search(r'\d+\s+(\w+)', tl); prod = m.group(1) if m else 'item'
            add_stock(uid, prod, qty, price); save_expense(uid, amount, text, 'restock')
            stock = dict(get_stock(uid)).get(prod,0)
            return f"Added {qty} {prod}. Stock now: {stock}"

    # SALE
    if mode=='sale' or any(k in tl for k in ['sold','sell']):
        nums = re.findall(r'(\d+)\s*(k|thousand)?', tl)
        qty, price = 1, 0
        if len(nums)>=2 and ('each' in tl or 'x' in tl):
            qty = int(nums[0][0]); price = int(nums[1][0])*(1000 if nums[1][1] else 1)
        elif nums: price = int(nums[0][0])*(1000 if nums[0][1] else 1)
        amount = qty*price
        m = re.search(r'\d+\s+(\w+)', tl); prod = m.group(1) if m else 'item'
        pay = 'transfer' if 'transfer' in tl else 'pos' if 'pos' in tl else 'cash'
        if amount>0:
            save_sale(uid, amount, prod, qty, pay)
            return f"Sold {qty} {prod} for ₦{amount:,}. Stock left: {dict(get_stock(uid)).get(prod,0)}"

    # EXPENSE
    if mode=='expense' or (re.search(r'\d', tl) and not any(k in tl for k in ['sold','sell'])):
        amount = extract_amount(tl)
        if amount>0:
            cat = classify_expense(text)
            if cat!='restock': save_expense(uid, amount, text, cat)
            return f"{cat.title()} ₦{amount:,} saved."

    return "Use the menu buttons."

@app.get("/webhook")
async def verify(request: Request):
    p = dict(request.query_params)
    return int(p.get("hub.challenge")) if p.get("hub.verify_token")==VERIFY_TOKEN else "fail"

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        msg = data['entry'][0]['changes'][0]['value']['messages'][0]
        uid = msg['from']

        if msg.get('type')=='interactive':
            bid = msg['interactive']['button_reply']['id']
            user_modes[uid]=bid
            if bid in ['sale','restock','expense']:
                send_whatsapp(uid, f"Mode: {bid}. Send details like '5 shirts each 7000'")
            elif bid=='stock':
                stock = get_stock(uid)
                txt = "\n".join([f"{p}: {q}" for p,q in stock]) if stock else "No stock yet"
                send_whatsapp(uid, f"Stock:\n{txt}"); send_report_menu(uid)
            elif bid in ['today','profit']:
                sales = get_period_sales(uid,'today'); restock = get_period_expenses(uid,'today','restock')
                profit = sales - restock
                send_whatsapp(uid, f"Today: Sales ₦{sales:,}, Profit ~₦{profit:,}"); send_menu(uid)
            return {"status":"ok"}

        text = msg['text']['body']
        if text.lower() in ['hi','menu','start']: send_menu(uid)
        else:
            resp = process_message(uid, text, user_modes.get(uid))
            send_whatsapp(uid, resp)
            if 'Welcome' not in resp: send_menu(uid)
    except Exception as e: print(e)
    return {"status":"ok"}
