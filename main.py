import os, re, requests
from fastapi import FastAPI, Request
from datetime import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from groq import Groq
from database import init_db, get_user, create_user, update_business_name, update_language, save_sale, save_expense, get_period_sales, get_period_expenses, get_best_product, delete_last_entry

app = FastAPI()
scheduler = BackgroundScheduler(timezone=pytz.timezone('Africa/Lagos'))
GROQ_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

LAGOS = pytz.timezone('Africa/Lagos')

@app.on_event("startup")
async def startup():
    init_db()
    scheduler.start()
    scheduler.add_job(send_daily_summary, 'cron', hour=21, minute=0)

def send_whatsapp(to, message):
    # FIXED URL
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "text": {"body": message}}
    r = requests.post(url, headers=headers, json=data)
    print(f"WHATSAPP SEND: {r.status_code} {r.text}")

def get_ai_advice(prompt, language='en'):
    if not groq_client:
        return "I don save am. Anything else?"
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

def extract_amount(text):
    m = re.search(r'(\d+)\s*(k|thousand)?', text)
    if not m: return 0
    return int(m.group(1)) * 1000 if m.group(2) else int(m.group(1))

def process_message(user_id, text):
    text_lower = text.lower().strip()
    user = get_user(user_id)

    if not user:
        create_user(user_id)
        return "Welcome to MarketBrain! What's your business name?"

    if not user['business_name']:
        update_business_name(user_id, text.title())
        return f"Nice! {text.title()} don enter. You wan make I dey speak Pidgin or English?"

    if not user['language']:
        lang = 'pidgin' if 'pidgin' in text_lower else 'en'
        update_language(user_id, lang)
        return "Perfect! Just send your sales like: 'sold 5 shirts each 7000' or 'rice 5000 cash'. I go track everything."

    if 'reset' in text_lower:
        from database import get_conn
        conn = get_conn(); c = conn.cursor()
        c.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
        c.execute("DELETE FROM sales WHERE user_id=%s", (user_id,))
        c.execute("DELETE FROM expenses WHERE user_id=%s", (user_id,))
        conn.commit(); conn.close()
        return "Reset done. Send hi to start again."

    if 'delete' in text_lower or 'undo' in text_lower:
        if delete_last_entry(user_id):
            return "Don delete am."
        return "Nothing to delete."

    # Reports
    if any(k in text_lower for k in ['how much', 'profit', 'make money', 'sales']):
        period = 'today' if 'today' in text_lower else 'yesterday' if 'yesterday' in text_lower else 'week'
        sales = get_period_sales(user_id, period)
        expenses = get_period_expenses(user_id, period, 'expense')
        restock = get_period_expenses(user_id, period, 'restock')
        profit = sales - expenses - restock
        return f"{period.title()}: Sales ₦{sales:,}, Expenses ₦{expenses:,}, Restock ₦{restock:,}. Profit: ₦{profit:,}"

    # Expenses / Restock
    expense_keywords = ['bought', 'spent', 'paid', 'fuel', 'transport', 'data', 'rent', 'stock', 'restock', 'inventory', 'buy']
    if any(k in text_lower for k in expense_keywords):
        nums = re.findall(r'(\d+)\s*(k|thousand)?', text_lower)
        if nums:
            if ('each' in text_lower or 'x' in text_lower) and len(nums) >= 2:
                q = int(nums[0][0]) * (1000 if nums[0][1] else 1)
                p = int(nums[1][0]) * (1000 if nums[1][1] else 1)
                amount = q * p
            else:
                amount = int(nums[0][0]) * 1000 if nums[0][1] else int(nums[0][0])
            expense_type = 'restock' if any(k in text_lower for k in ['stock','restock','inventory','buy','bought']) else 'expense'
            save_expense(user_id, amount, text, expense_type)
            return f"Saved {expense_type} ₦{amount:,}. Well done!"

    # SALES - NEW BULK SUPPORT
    is_sale = any(k in text_lower for k in ['sold', 'sell', 'sale']) or any(p in text_lower for p in ['cash','transfer','pos'])
    if is_sale and not any(k in text_lower for k in expense_keywords):
        nums = re.findall(r'(\d+)\s*(k|thousand)?', text_lower)
        amount = 0
        product = 'item'

        # "sold 5 shirts each 7000"
        if ('each' in text_lower or 'x' in text_lower) and len(nums) >= 2:
            qty = int(nums[0][0]) * (1000 if nums[0][1] else 1)
            price = int(nums[1][0]) * (1000 if nums[1][1] else 1)
            amount = qty * price
            # find product name between qty and each
            m = re.search(r'\d+\s+(\w+)', text_lower)
            if m: product = m.group(1)
        elif nums:
            amount = int(nums[0][0]) * 1000 if nums[0][1] else int(nums[0][0])
            for w in ['shirt','shirts','oud','perfume','dress','shoe','bag','rice']:
                if w in text_lower: product = w; break

        payment = 'cash'
        if 'transfer' in text_lower: payment = 'transfer'
        elif 'pos' in text_lower: payment = 'pos'

        if amount > 0:
            save_sale(user_id, amount, product, payment)
            total = get_period_sales(user_id, 'today')
            return f"₦{amount:,} saved! Today total: ₦{total:,}. Keep am up!"

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
    pass
