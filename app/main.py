from fastapi import FastAPI, Request
import requests, os, sqlite3
from dotenv import load_dotenv
from database import *
from ai_parser import *
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

load_dotenv()
app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "marketbrain123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

init_db()

# --- LANGUAGES ---
LANG = {
    'en': {
        'ask_name': "Welcome to MarketBrain! What's your business name?",
        'ask_lang': "Choose language:\n1. Pidgin\n2. English",
        'confirm': "Perfect! Tracking for *{name}*.\n\nTry: 'rice 5000 cash' or ask 'am I making money?'",
        'saved': "✅ Saved {n}. Ask 'am I making money?' for CFO report",
        'cfo': "📊 {name} CFO ({period})\n\nSales: N{sales:,}\nStock cost: N{cogs:,}\nGross: N{gross:,}\nOverhead: N{o:,}\n*Net Profit: N{net:,} ({margin}%)*\n\nCash: N{cash:,} | Transfer: N{trf:,}\nTop: {best}\n\n💡 {tip}"
    },
    'pidgin': {
        'ask_name': "Welcome to MarketBrain! Wetin be your business name?",
        'ask_lang': "Choose language:\n1. Pidgin\n2. English",
        'confirm': "Correct! I go dey track for *{name}*.\n\nTry: 'rice 5000 cash' or ask 'I dey make money?'",
        'saved': "✅ I don save {n}. Ask 'I dey make money?' to see report",
        'cfo': "📊 {name} CFO ({period})\n\nSales: N{sales:,}\nStock cost: N{cogs:,}\nGross: N{gross:,}\nOverhead: N{o:,}\n*Net Profit: N{net:,} ({margin}%)*\n\nCash: N{cash:,} | Transfer: N{trf:,}\nTop: {best}\n\n💡 {tip}"
    }
}

TIPS = {
    'en': {'good':"Good margin, keep pushing", 'high':"Costs high, check your stock prices", 'over':"Watch overhead costs"},
    'pidgin': {'good':"Your margin good, keep am up", 'high':"Cost too high, check price wey you dey buy", 'over':"Reduce your spendings small"}
}

def t(user, key, **k):
    lang = user.get('language') or 'pidgin'
    return LANG[lang][key].format(**k)

def send_message(to, text):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "text": {"body": text}}
    requests.post(url, headers=headers, json=data)

# --- DAILY SUMMARY ---
def daily_summary_job():
    conn = sqlite3.connect(DB_PATH)
    users = conn.execute("SELECT user_id, business_name, language FROM users").fetchall()
    conn.close()
    for uid, name, lang in users:
        s = get_period_sales(uid, 'today')
        c = get_period_expenses(uid, 'today', 'cogs')
        o = get_period_expenses(uid, 'today', 'overhead')
        if s > 0:
            net = s - c - o
            lang = lang or 'pidgin'
            if lang == 'pidgin':
                msg = f"📊 {name or 'Your Biz'}\nToday: Sales N{s:,} - Stock N{c:,} - Exp N{o:,} = *Profit N{net:,}*"
            else:
                msg = f"📊 {name or 'Your Business'}\nToday Profit: N{net:,} (Sales N{s:,})"
            send_message(uid, msg)

scheduler = BackgroundScheduler(timezone=pytz.timezone('Africa/Lagos'))
scheduler.add_job(daily_summary_job, CronTrigger(hour=21, minute=0))

@app.on_event("startup")
def start_scheduler():
    scheduler.start()
    print("Scheduler started")

@app.get("/webhook")
async def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(params.get("hub.challenge"))
    return "error"

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        value = data["entry"][0]["changes"][0]["value"]
        if "messages" not in value:
            return {"status": "ok"}

        msg = value["messages"][0]
        uid = msg["from"]
        msg_type = msg["type"]

        # --- ONBOARDING ---
        user = get_user(uid)
        if not user:
            create_user(uid)
            send_message(uid, LANG['pidgin']['ask_name'])
            return {"status": "ok"}

        if not user['business_name']:
            if msg_type == "text":
                name = msg["text"]["body"].strip()
                if len(name) < 40:
                    update_business_name(uid, name)
                    send_message(uid, LANG['pidgin']['ask_lang'])
            return {"status": "ok"}

        if not user['language']:
            if msg_type == "text":
                choice = msg["text"]["body"].strip()
                lang = 'pidgin' if choice.startswith('1') else 'en'
                update_language(uid, lang)
                user = get_user(uid)
                send_message(uid, t(user, 'confirm', name=user['business_name']))
            return {"status": "ok"}

        # --- GET TEXT ---
        text = ""
        if msg_type == "text":
            text = msg["text"]["body"]
        elif msg_type == "audio":
            media_id = msg["audio"]["id"]
            url = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}).json()["url"]
            text = transcribe_audio(url)
        elif msg_type == "image":
            media_id = msg["image"]["id"]
            url = requests.get(f"https://graph.facebook.com/v19.0/{media_id}", headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}).json()["url"]
            text = extract_text_from_image(url, WHATSAPP_TOKEN)

        if not text:
            return {"status": "ok"}
        
        tl = text.lower()
        user = get_user(uid) # refresh
        lang = user['language'] or 'pidgin'

        # --- UNDO / FIX COMMANDS ---
        undo_words = ['undo','delete last','comot last','remove last','cancel last']
        if any(w in tl for w in undo_words):
            deleted = delete_last_entry(uid)
            lang = user['language'] or 'pidgin'
            if deleted:
                msg = "Last entry don comot." if lang=='pidgin' else "Last entry deleted."
            else:
                msg = "Nothing to delete." if lang=='en' else "Nothing to comot."
            send_message(uid, msg)
            return {"status": "ok"}

        if tl.startswith('change name to'):
            new_name = text.split('to',1)[1].strip()
            if new_name:
                update_business_name(uid, new_name)
                msg = f"Name changed to {new_name}" if lang=='en' else f"Name don change to {new_name}"
                send_message(uid, msg)
            return {"status": "ok"}

        if 'change language' in tl:
            update_language(uid, None)
            send_message(uid, LANG['pidgin']['ask_lang'])
            return {"status": "ok"}

        if tl.startswith('correct last to'):
            # simple version: delete and re-add
            delete_last_entry(uid)
            # fall through to normal save with the new text
            text = text.split('to',1)[1]
            tl = text.lower()

        # --- CFO QUERY ---
        cfo_words = ['p&l','p and l','making money','cfo','profit','am i','i dey make','make money','show report']
        if any(w in tl for w in cfo_words):
            period = 'week' if 'week' in tl else 'yesterday' if 'yesterday' in tl else 'today'
            period_name = period if lang=='en' else {'today':'today','week':'this week','yesterday':'yesterday'}[period]

            s = get_period_sales(uid, period)
            c = get_period_expenses(uid, period, 'cogs')
            o = get_period_expenses(uid, period, 'overhead')
            gross = s - c
            net = gross - o
            margin = int(net / s * 100) if s > 0 else 0
            cash = get_period_sales(uid, period, pay='cash')
            trf = get_period_sales(uid, period, pay='transfer')
            best = get_best_product(uid, period)

            tip = TIPS[lang]['good'] if margin > 20 else TIPS[lang]['high'] if c > s * 0.6 else TIPS[lang]['over']

            reply = t(user, 'cfo', name=user['business_name'], period=period_name, sales=s, cogs=c, gross=gross, o=o, net=net, margin=margin, cash=cash, trf=trf, best=best, tip=tip)
            send_message(uid, reply)
            return {"status": "ok"}

        # --- SAVE DATA ---
        saved = 0
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            total, _ = extract_amounts(line)
            if total == 0:
                continue

            if any(k in line.lower() for k in ['spent','spend','buy','restock','purchase','bought']):
                exp_type = detect_expense_type(line)
                save_expense(uid, total, extract_product(line), exp_type)
            else:
                save_sale(uid, total, extract_product(line), extract_payment_method(line))
            saved += 1

        if saved > 0:
            send_message(uid, t(user, 'saved', n=saved))

    except Exception as e:
        print(f"ERROR: {e}")
    return {"status": "ok"}