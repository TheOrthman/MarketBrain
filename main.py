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

@app.on_event("startup")
async def startup():
    init_db()
    # scheduler.start()  # disabled for now

def send_whatsapp(to, message):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "text": {"body": message}}
    try:
        r = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"WHATSAPP_DEBUG TO={to} CODE={r.status_code} BODY={r.text}")
    except Exception as e:
        print(f"WHATSAPP_ERROR {e}")

def process_message(user_id, text):
    text = text.lower().strip()
    user = get_user(user_id)
    if not user:
        create_user(user_id)
        return "Welcome to MarketBrain! What's your business name?"
    if not user['business_name']:
        update_business_name(user_id, text.title())
        return f"Nice! {text.title()} don enter. Pidgin or English?"
    if not user['language']:
        update_language(user_id, 'pidgin' if 'pidgin' in text else 'en')
        return "Perfect! Send sales like 'sold 2 shirts 5000' or stock like 'stock 10 shirts 3000'"

    if text in ['stock', 'inventory'] or ('how many' in text and 'left' in text):
        items = get_all_stock(user_id)
        if not items: return "No stock yet. Add with 'stock 10 shirts 3000'"
        return "\n".join([f"{r['product'].title()}: {r['quantity']} left" for r in items])

    restock_match = re.search(r'(bought|buy|restock|stock)\s+(\d+)\s+([a-z0-9 ]+?)\s+(?:at\s+)?(\d+)\s*(k|thousand)?', text)
    if restock_match:
        qty = int(restock_match.group(2))
        product = restock_match.group(3).strip()
        unit = int(restock_match.group(4)) * 1000 if restock_match.group(5) else int(restock_match.group(4))
        total = qty * unit
        save_expense(user_id, total, f"{qty} {product}", 'restock')
        add_stock(user_id, product, qty, unit)
        current = get_stock(user_id, product)
        return f"Added {qty} {product} @ ₦{unit:,}. You now have {current} {product}."

    sale_qty_match = re.search(r'(sold|sell)\s+(\d+)\s+([a-z0-9 ]+?)\s+(\d+)\s*(k|thousand)?', text)
    if sale_qty_match:
        qty = int(sale_qty_match.group(2))
        product = sale_qty_match.group(3).strip()
        price = int(sale_qty_match.group(4)) * 1000 if sale_qty_match.group(5) else int(sale_qty_match.group(4))
        total = qty * price
        payment = 'cash' if 'cash' in text else 'transfer' if 'transfer' in text else 'cash'
        save_sale(user_id, total, product, payment, qty)
        remaining = remove_stock(user_id, product, qty)
        warn = f" ⚠️ Only {remaining} left! Restock soon." if remaining <= 5 else ""
        return f"Sold {qty} {product} for ₦{total:,}. Stock left: {remaining}.{warn}"

    if any(k in text for k in ['cash','transfer','pos']) and re.search(r'\d', text):
        amt = re.search(r'(\d+)\s*(k|thousand)?', text)
        if amt:
            amount = int(amt.group(1)) * 1000 if amt.group(2) else int(amt.group(1))
            product = text.replace(amt.group(0),'').replace('cash','').replace('transfer','').strip() or 'item'
            save_sale(user_id, amount, product, 'cash', 1)
            remove_stock(user_id, product, 1)
            return f"₦{amount:,} saved!"

    if 'profit' in text or 'how much' in text:
        sales = get_period_sales(user_id, 'today')
        exp = get_period_expenses(user_id, 'today', 'expense')
        rest = get_period_expenses(user_id, 'today', 'restock')
        return f"Today: Sales ₦{sales:,}, Expenses ₦{exp:,}, Restock ₦{rest:,}. Profit ₦{sales-exp-rest:,}"

    return "Got it. Send 'stock' to check inventory."

@app.get("/webhook")
async def verify(request: Request):
    p = dict(request.query_params)
    return int(p.get("hub.challenge")) if p.get("hub.verify_token") == VERIFY_TOKEN else "fail"

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        msg = data['entry'][0]['changes'][0]['value']['messages'][0]
        resp = process_message(msg['from'], msg['text']['body'])
        send_whatsapp(msg['from'], resp)
    except: pass
    return {"status":"ok"}
