import os, re, requests, traceback, cv2
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
    init_db()
    scheduler.start()

def send_whatsapp(to, msg):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": msg}}
    r = requests.post(url, headers=headers, json=payload)
    print(f"SEND {r.status_code} {r.text[:100]}")

def send_menu(to):
    send_whatsapp(to, "MarketBrain:\n1 💰 Sale\n2 📦 Stock\n3 💸 Expense\n4 📊 Reports\n5 📷 Scan sales\n\nReply number")

def transcribe_audio(media_id):
    try:
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        meta = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers=headers).json()
        audio_url = meta.get('url')
        if not audio_url: return ""
        audio = requests.get(audio_url, headers=headers).content
        with open('/tmp/voice.ogg', 'wb') as f: f.write(audio)
        with open('/tmp/voice.ogg', 'rb') as f:
            resp = groq_client.audio.transcriptions.create(file=f, model="whisper-large-v3")
        return resp.text if hasattr(resp, 'text') else str(resp)
    except Exception as e:
        print("Transcribe fail:", e)
        traceback.print_exc()
        return ""

def download_media(media_id):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    meta = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers=headers).json()
    url = meta.get('url')
    data = requests.get(url, headers=headers).content
    path = f"/tmp/{media_id}.jpg"
    with open(path, 'wb') as f: f.write(data)
    return path

def preprocess_image(path):
    img = cv2.imread(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced = clahe.apply(gray)
    out = f"{path}_p.jpg"
    cv2.imwrite(out, enhanced)
    return out

def extract_sales_from_image(path):
    proc = preprocess_image(path)
    result = ocr.ocr(proc, cls=True)
    lines = []
    for line in result[0]:
        txt = line[1][0].strip().lower()
        if len(txt) > 2:
            lines.append(txt)
    sales = []
    for l in lines:
        m = re.search(r'([a-z]+)\s*x?(\d+)\s*(\d+)', l)
        if m:
            item, qty, price = m.groups()
            sales.append({"item":item, "qty":int(qty), "price":int(price), "total":int(qty)*int(price), "raw":l})
    return sales

def extract_amount(t):
    m = re.search(r'(\d+)\s*(k|thousand)?', t, re.I)
    return int(m.group(1)) * (1000 if m.group(2) else 1) if m else 0

def process_message(uid, text, mode):
    # your existing function unchanged
    user = get_user(uid)
    tl = text.lower()
    if 'reset' in tl:
        conn = get_conn(); c = conn.cursor()
        for tbl in ['sales', 'expenses', 'inventory', 'users']:
            c.execute(f"DELETE FROM {tbl} WHERE user_id = %s", (uid,))
        conn.commit(); conn.close()
        create_user(uid)
        return "RESET"
    if not user:
        create_user(uid)
        return "Welcome! What's your business name?"
    if not user['business_name']:
        update_business_name(uid, text.title())
        return "__ASK_LANG__"
    if not user['language']:
        lang = 'pidgin' if 'pidgin' in tl else 'en'
        update_language(uid, lang)
        return "__SHOW_MENU__"
    if mode == '4' or 'report' in tl:
        sales_today = get_period_sales(uid, 'today')
        sales_week = get_period_sales(uid, 'week')
        exp_today = get_period_expenses(uid, 'today', 'expense')
        exp_restock = get_period_expenses(uid, 'today', 'restock')
        stock = get_stock(uid)
        stock_txt = "\n".join([f"• {p}: {q}" for p, q in stock[:5]]) if stock else "No stock recorded"
        profit = sales_today - exp_restock
        return f"📊 TODAY'S REPORT\n\n💰 Sales: ₦{sales_today:,}\n💸 Expenses: ₦{exp_today:,}\n📦 Restock: ₦{exp_restock:,}\n📈 Profit: ₦{profit:,}\n\nWeek Sales: ₦{sales_week:,}\n\nSTOCK:\n{stock_txt}"
    if mode == '2' or 'bought' in tl or 'restock' in tl:
        nums = re.findall(r'(\d+)', tl)
        if len(nums) >= 2:
            q, p = int(nums[0]), int(nums[1]) * 1000
            add_stock(uid, 'item', q, p)
            save_expense(uid, q * p, text, 'restock')
            return f"✅ Added {q} items (₦{p:,} each)"
        return "Send: quantity price (e.g. '20 5k')"
    if mode == '1' or 'sold' in tl or 'sale' in tl:
        nums = re.findall(r'(\d+)', tl)
        a = int(nums[0]) * 1000 if nums else extract_amount(tl)
        if a:
            save_sale(uid, a, 'item', 1, 'cash')
            return f"✅ Sale ₦{a:,} saved"
        return "Send amount (e.g. '15k')"
    if mode == '3' or 'expense' in tl or 'spent' in tl:
        a = extract_amount(tl)
        if a:
            save_expense(uid, a, text, 'expense')
            return f"✅ Expense ₦{a:,} saved"
        return "Send amount (e.g. 'transport 2k')"
    return "Saved. Choose from menu."

@app.get("/webhook")
async def verify(r: Request):
    p = dict(r.query_params)
    if p.get("hub.verify_token") == VERIFY_TOKEN:
        return int(p.get("hub.challenge"))
    return "fail"

@app.post("/webhook")
async def webhook(r: Request):
    try:
        data = await r.json()
        value = data['entry'][0]['changes'][0]['value']
        if 'messages' not in value:
            return {"status": "ok"}
        msg = value['messages'][0]
        uid = msg['from']

        if msg.get('type') == 'image':
            send_whatsapp(uid, "📷 Scanning your sales...")
            path = download_media(msg['image']['id'])
            sales = extract_sales_from_image(path)
            if sales:
                total = sum(s['total'] for s in sales)
                txt = f"I see {len(sales)} sales:\n"
                for i,s in enumerate(sales,1):
                    txt += f"{i}. {s['item'].title()} x{s['qty']} = ₦{s['total']:,}\n"
                txt += f"\nTotal: ₦{total:,}\nReply 1 to save all"
                user_modes[uid] = 'scan_pending'
                # store temporarily
                app.state.scan_cache = getattr(app.state, 'scan_cache', {})
                app.state.scan_cache[uid] = sales
                send_whatsapp(uid, txt)
            else:
                send_whatsapp(uid, "Couldn't read it. Try brighter light, one item per line.")
            return {"status":"ok"}

        if msg.get('type') == 'audio':
            send_whatsapp(uid, "🎤 Listening...")
            txt = transcribe_audio(msg['audio']['id'])
            if txt:
                send_whatsapp(uid, f"You said: {txt}")
                resp = process_message(uid, txt, user_modes.get(uid))
                send_whatsapp(uid, resp)
            else:
                send_whatsapp(uid, "Couldn't hear. Try typing.")
            send_menu(uid)
            return {"status": "ok"}

        if msg.get('type') == 'text':
            text = msg['text']['body'].strip()

            # handle scan confirmation
            if user_modes.get(uid) == 'scan_pending' and text == '1':
                sales = app.state.scan_cache.get(uid, [])
                for s in sales:
                    save_sale(uid, s['total'], s['item'], s['qty'], 'cash')
                user_modes[uid] = None
                send_whatsapp(uid, f"✅ Saved {len(sales)} sales!")
                send_menu(uid)
                return {"status":"ok"}

            if text in ['1','2','3','4','5']:
                user_modes[uid] = text
                if text == '4':
                    resp = process_message(uid, 'report', '4')
                    send_whatsapp(uid, resp)
                    send_menu(uid)
                elif text == '5':
                    send_whatsapp(uid, "Send a clear photo of your sales book. Write one per line like 'Peak 2 1500'")
                else:
                    names = {'1':'Sale','2':'Stock','3':'Expense'}
                    send_whatsapp(uid, f"{names[text]} mode. Send details")
                return {"status": "ok"}

            if text.lower() in ['hi','hello','menu','start']:
                send_menu(uid)
                return {"status": "ok"}

            resp = process_message(uid, text, user_modes.get(uid))
            if resp == "RESET":
                send_whatsapp(uid, "✅ Reset done! What's your business name?")
            elif resp == "__ASK_LANG__":
                send_whatsapp(uid, "Great! Reply: Pidgin or English")
            elif resp == "__SHOW_MENU__":
                send_whatsapp(uid, "You're all set! 🎉")
                send_menu(uid)
            else:
                send_whatsapp(uid, resp)
                if user_modes.get(uid) not in ['4','scan_pending']:
                    send_menu(uid)
    except Exception as e:
        print("ERR", e)
        traceback.print_exc()
    return {"status": "ok"}