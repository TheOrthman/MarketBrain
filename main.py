import os, re, requests
from fastapi import FastAPI, Request
from datetime import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from groq import Groq
from database import init_db, get_user, create_user, update_business_name, update_language, save_sale, save_expense, get_period_sales, get_period_expenses, delete_last_entry

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
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "text": {"body": message}}
    requests.post(url, headers=headers, json=data)

def extract_amount(text):
    m = re.search(r'(\d+)\s*(k|thousand)?', text)
    if not m: return 0
    return int(m.group(1)) * 1000 if m.group(2) else int(m.group(1))

def classify_expense(description):
    """AI categorizes any expense"""
    if not groq_client:
        return 'expense'
    try:
        prompt = f"Classify this Nigerian trader expense into ONE word: restock, packaging, transport, delivery, fuel, rent, data, marketing, feeding, other. Text: '{description}'"
        resp = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role":"user","content":prompt}],
            max_tokens=5,
            temperature=0
        )
        cat = resp.choices[0].message.content.strip().lower()
        return cat if cat in ['restock','packaging','transport','delivery','fuel','rent','data','marketing','feeding'] else 'expense'
    except:
        return 'expense'

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
        return "Perfect! Send sales like 'sold 5 shirts each 7000'. Send expenses like 'packaging 2k' or 'fuel 3k'."

    if 'reset' in text_lower:
        from database import get_conn
        conn = get_conn(); c = conn.cursor()
        for t in ['users','sales','expenses']: c.execute(f"DELETE FROM {t} WHERE user_id=%s",(user_id,))
        conn.commit(); conn.close()
        return "Reset done."
    if 'delete' in text_lower or 'undo' in text_lower:
        return "Don delete am." if delete_last_entry(user_id) else "Nothing to delete."

    # Reports
    if any(k in text_lower for k in ['how much','profit','report']):
        period = 'today' if 'today' in text_lower else 'yesterday' if 'yesterday' in text_lower else 'week'
        sales = get_period_sales(user_id, period)
        expenses = get_period_expenses(user_id, period, 'expense')
        restock = get_period_expenses(user_id, period, 'restock')
        # get all categories
        packaging = get_period_expenses(user_id, period, 'packaging')
        profit = sales - expenses - restock - packaging
        if user['language']=='pidgin':
            return f"{period.title()}: Sales ₦{sales:,}, Restock ₦{restock:,}, Packaging ₦{packaging:,}, Profit ₦{profit:,}"
        return f"{period.title()} - Sales: ₦{sales:,}, Restock: ₦{restock:,}, Packaging: ₦{packaging:,}, Profit: ₦{profit:,}"

    # Detect sale intent
    is_sale = any(k in text_lower for k in ['sold','sell']) or any(p in text_lower for p in ['cash','transfer','pos'])

    # EXPENSES - now catches ANYTHING with money that's not a sale
    if not is_sale and re.search(r'\d', text_lower):
        nums = re.findall(r'(\d+)\s*(k|thousand)?', text_lower)
        amount = 0
        if ('each' in text_lower or 'x' in text_lower) and len(nums)>=2:
            amount = (int(nums[0][0])*(1000 if nums[0][1] else 1)) * (int(nums[1][0])*(1000 if nums[1][1] else 1))
        elif nums:
            amount = int(nums[0][0])*(1000 if nums[0][1] else 1)

        if amount>0:
            category = classify_expense(text)
            # force restock if obvious
            if any(k in text_lower for k in ['stock','buy','bought','restock','inventory']):
                category = 'restock'
            save_expense(user_id, amount, text, category)
            if user['language']=='pidgin':
                return f"{category.title()} ₦{amount:,} don enter. I dey track am!"
            return f"{category.title()} ₦{amount:,} recorded."

    # SALES
    if is_sale:
        nums = re.findall(r'(\d+)\s*(k|thousand)?', text_lower)
        amount = 0
        product = 'item'
        if ('each' in text_lower or 'x' in text_lower) and len(nums)>=2:
            qty = int(nums[0][0])*(1000 if nums[0][1] else 1)
            price = int(nums[1][0])*(1000 if nums[1][1] else 1)
            amount = qty*price
            m = re.search(r'\d+\s+(\w+)', text_lower)
            if m: product = m.group(1)
        elif nums:
            amount = int(nums[0][0])*(1000 if nums[0][1] else 1)

        payment = 'transfer' if 'transfer' in text_lower else 'pos' if 'pos' in text_lower else 'cash'
        if amount>0:
            save_sale(user_id, amount, product, payment)
            total = get_period_sales(user_id, 'today')
            return f"₦{amount:,} saved! Today: ₦{total:,}"

    # AI fallback
    if groq_client:
        lang_inst = "Pidgin" if user['language']=='pidgin' else "English"
        resp = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role":"system","content":f"Answer in {lang_inst}, under 2 sentences."},
                      {"role":"user","content":text}],
            max_tokens=80
        )
        return resp.choices[0].message.content
    return "I don save am."

@app.get("/webhook")
async def verify(request: Request):
    p = dict(request.query_params)
    return int(p.get("hub.challenge")) if p.get("hub.verify_token")==VERIFY_TOKEN else "failed"

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        msg = data['entry'][0]['changes'][0]['value']['messages'][0]
        resp = process_message(msg['from'], msg['text']['body'])
        send_whatsapp(msg['from'], resp)
    except Exception as e:
        print(f"Error: {e}")
    return {"status":"ok"}

def send_daily_summary(): pass
