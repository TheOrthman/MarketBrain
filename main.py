from fastapi import FastAPI, Request
import requests
import os
import sqlite3
from datetime import datetime

app = FastAPI()

# --- CONFIG ---
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "marketbrain2026")

# Load WhatsApp token (env, secret file, or hardcoded fallback)
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
if len(WHATSAPP_TOKEN) < 100:
    try:
        with open("/etc/secrets/whatsapp_token", "r") as f:
            WHATSAPP_TOKEN = f.read().strip()
    except:
        # Hardcoded permanent token (works for demo)
        WHATSAPP_TOKEN = "EAAUnBKSsSJIBReab5jKx5cCpfLL2bBBtuaps8xxESOtZANMgBLZCKXo20S5b4WM3YhWnTL6Kkx4QqZCw1evkbI25wGH8sAeFrMAquK7jURb2qcTdoRVIcZArjhYKHRAkaJhBBh0QMSkpZBL1pTavQeR3SOYWfAqZAP2ZBfsUxxyNKxd0UIRx6FWZCjFMFhPJrgZDZD"

PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1114871821711140")

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect("marketbrain.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS stock (id INTEGER PRIMARY KEY, phone TEXT, item TEXT, qty INTEGER, cost REAL, date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY, phone TEXT, item TEXT, qty INTEGER, price REAL, date TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- WHATSAPP SEND ---
def send_whatsapp(to, message):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": message}}
    try:
        r = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"SEND TO {to} -> {r.status_code}")
    except Exception as e:
        print(f"ERROR: {e}")

# --- BUSINESS LOGIC ---
def handle_message(phone, text):
    text = text.lower().strip()
    conn = sqlite3.connect("marketbrain.db")
    c = conn.cursor()

    if text in ["hi", "hello", "menu"]:
        return "🧠 MarketBrain\n\n1. stock [qty] [item] [cost] - Add stock\n2. sell [qty] [item] [price] - Record sale\n3. profit - Today's profit\n4. stock list - View inventory\n5. price [qty] [item] [cost] - Suggest price\n\nExample: stock 10 shirts 3000"

    if text.startswith("stock ") and " " in text[6:]:
        try:
            parts = text.split()
            qty = int(parts[1])
            cost = float(parts[-1])
            item = " ".join(parts[2:-1])
            c.execute("INSERT INTO stock (phone, item, qty, cost, date) VALUES (?,?,?,?,?)",
                     (phone, item, qty, cost, datetime.now().strftime("%Y-%m-%d")))
            conn.commit()
            return f"✅ Added {qty} {item} at ₦{cost:,.0f} each"
        except:
            return "Format: stock 10 shirts 3000"

    if text.startswith("sell "):
        try:
            parts = text.split()
            qty = int(parts[1])
            price = float(parts[-1])
            item = " ".join(parts[2:-1])
            c.execute("INSERT INTO sales (phone, item, qty, price, date) VALUES (?,?,?,?,?)",
                     (phone, item, qty, price, datetime.now().strftime("%Y-%m-%d")))
            conn.commit()
            return f"✅ Sold {qty} {item} at ₦{price:,.0f} each"
        except:
            return "Format: sell 5 shirts 5000"

    if text == "profit":
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("SELECT SUM(qty*price) FROM sales WHERE phone=? AND date=?", (phone, today))
        revenue = c.fetchone()[0] or 0
        c.execute("SELECT SUM(qty*cost) FROM stock WHERE phone=? AND date=?", (phone, today))
        cost = c.fetchone()[0] or 0
        profit = revenue - cost
        return f"💰 Today: ₦{profit:,.0f} profit\nRevenue: ₦{revenue:,.0f}\nCost: ₦{cost:,.0f}"

    if text == "stock list":
        c.execute("SELECT item, SUM(qty) FROM stock WHERE phone=? GROUP BY item", (phone,))
        stocks = c.fetchall()
        if not stocks: return "No stock yet"
        return "📦 Stock:\n" + "\n".join([f"{item}: {qty}" for item, qty in stocks])

    if text.startswith("price "):
        try:
            parts = text.split()
            qty = int(parts[1])
            cost = float(parts[-1])
            item = " ".join(parts[2:-1])
            suggested = cost * 1.4 # 40% markup
            return f"💡 {item}:\nCost: ₦{cost:,.0f}\nSuggested sell: ₦{suggested:,.0f} (40% profit)\nFor {qty} units: ₦{suggested*qty:,.0f} total"
        except:
            return "Format: price 10 shirts 3000"

    conn.close()
    return "Type 'hi' for menu"

# --- WEBHOOK ---
@app.get("/")
def home():
    return {"status": "MarketBrain running"}

@app.get("/webhook")
def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(params.get("hub.challenge", 0))
    return "Invalid"

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        entry = data["entry"][0]["changes"][0]["value"]
        if "messages" in entry:
            msg = entry["messages"][0]
            phone = msg["from"]
            text = msg["text"]["body"]
            reply = handle_message(phone, text)
            send_whatsapp(phone, reply)
    except Exception as e:
        print(f"Webhook error: {e}")
    return {"status": "ok"}
