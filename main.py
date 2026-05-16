import os, re, requests
from fastapi import FastAPI, Request
from datetime import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from groq import Groq
from database import init_db, get_user, create_user, update_business_name, update_language, save_sale, save_expense, get_period_sales, get_period_expenses, get_best_product, delete_last_entry

app = FastAPI()
scheduler = BackgroundScheduler(timezone=pytz.timezone('Africa/Lagos'))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --- FIXED TOKEN LOADING ---
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
if len(WHATSAPP_TOKEN) < 100:
    try:
        with open("/etc/secrets/whatsapp_token", "r") as f:
            WHATSAPP_TOKEN = f.read().strip()
    except:
        WHATSAPP_TOKEN = "EAAUnBKSsSJIBReab5jKx5cCpfLL2bBBtuaps8xxESOtZANMgBLZCKXo20S5b4WM3YhWnTL6Kkx4QqZCw1evkbI25wGH8sAeFrMAquK7jURb2qcTdoRVIcZArjhYKHRAkaJhBBh0QMSkpZBL1pTavQeR3SOYWfAqZAP2ZBfsUxxyNKxd0UIRx6FWZCjFMFhPJrgZDZD"

PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1114871821711140")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "marketbrain2026")

LAGOS = pytz.timezone('Africa/Lagos')

@app.on_event("startup")
async def startup():
    init_db()
    scheduler.start()
    scheduler.add_job(send_daily_summary, 'cron', hour=21, minute=0)

def send_whatsapp(to, message):
    # FIXED URL - removed double https
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "text": {"body": message}}
    try:
        r = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"WHATSAPP {to} -> {r.status_code}")
    except Exception as e:
        print(f"Send error: {e}")

def get_ai_advice(prompt, language='en'):
    try:
        lang_instruction = "Respond in Nigerian Pidgin." if language == 'pidgin' else "Respond in simple English."
        response = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "system", "content": f"You are MarketBrain, a business assistant for Nigerian market traders. {lang_instruction} Keep responses under 3 sentences."},
                      {"role": "user", "content": prompt}],
            max_tokens=150
        )
        return response.choices[0].message.content
    except:
        return "I don save am. Anything else?"

def process_message(user_id, text):
    text = text.lower().strip()
    user = get_user(user_id)

    if not user:
        create_user(user_id)
        return "Welcome to MarketBrain! What's your business name?"

    if not user['business_name']:
        update_business_name(user_id, text.title())
        return f"Nice! {text.title()} don enter. You wan make I dey speak Pidgin or English?"

    if not user['language']:
        lang = 'pidgin' if 'pidgin' in text else 'en'
        update_language(user_id, lang)
        return "Perfect! Just send your sales like: 'rice 5000 cash' or 'Sold perfume 15000'. I go track everything."

    # Delete
    if 'delete' in text or 'undo' in text:
        if delete_last_entry(user_id):
            return "Don delete am."
        return "Nothing to delete."

    # Reports
    if any(k in text for k in ['how much', 'profit', 'make money', 'sales']):
        period = 'today' if 'today' in text else 'yesterday' if 'yesterday' in text else 'week'
        sales = get_period_sales(user_id, period)
        expenses = get_period_expenses(user_id, period, 'expense')
        restock = get_period_expenses(user_id, period, 'restock')
        profit = sales - expenses - restock
        return f"{period.title()}: Sales ₦{sales:,}, Expenses ₦{expenses:,}, Restock ₦{restock:,}. Profit: ₦{profit:,}"

    # Parse expenses/restock
    expense_keywords = ['bought', 'spent', 'paid', 'fuel', 'transport', 'data', 'rent', 'stock', 'restock', 'inventory', 'buy']
    if any(k in text for k in expense_keywords):
        amount_match = re.search(r'(\d+)\s*(k|thousand)?', text)
        if amount_match:
            amount = int(amount_match.group(1)) * 1000 if amount_match.group(2) else int(amount_match.group(1))
            expense_type = 'restock' if any(k in text for k in ['stock','restock','inventory','buy','bought']) else 'expense'
            save_expense(user_id, amount, text, expense_type)
            return f"Saved {expense_type} ₦{amount:,}. Well done!"

    # Parse sales
    sale_match = re.search(r'(\d+)\s*(k|thousand)?', text)
    payment = 'cash' if 'cash' in text else 'transfer' if 'transfer' in text else 'pos' if 'pos' in text else 'cash'
    is_sale_intent = any(k in text for k in ['sold', 'sell', 'sale']) or payment in text

    if sale_match and is_sale_intent and not any(k in text for k in expense_keywords):
        amount = int(sale_match.group(1)) * 1000 if sale_match.group(2) else int(sale_match.group(1))
        product = text.replace(str(sale_match.group(1)), '').replace('k','').replace('sold','').replace('sell','').replace(payment,'').strip()
        product = product if product else 'item'
        save_sale(user_id, amount, product, payment)
        sales_today = get_period_sales(user_id, 'today')
        return f"₦{amount:,} saved! Today total: ₦{sales_today:,}. Keep am up!"

    # AI fallback
    return get_ai_advice(text, user['language'])

@app.get("/webhook")
async def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(params.get("hub.challenge"))
    return "Verification failed"

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        entry = data['entry'][0]['changes'][0]['value']
        if 'messages' in entry:
            msg = entry['messages'][0]
            user_id = msg['from']
            text = msg['text']['body']
            response = process_message(user_id, text)
            send_whatsapp(user_id, response)
    except Exception as e:
        print(f"Error: {e}")
    return {"status": "ok"}

def send_daily_summary():
    # placeholder for daily job
    pass
