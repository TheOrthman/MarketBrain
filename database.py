import os, psycopg2
from datetime import datetime, timedelta
import pytz

DATABASE_URL = os.getenv("DATABASE_URL")
LAGOS = pytz.timezone('Africa/Lagos')

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_conn(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, business_name TEXT, language TEXT, created_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales (id SERIAL PRIMARY KEY, user_id TEXT, amount INTEGER, product TEXT, quantity INTEGER, payment_method TEXT, timestamp TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (id SERIAL PRIMARY KEY, user_id TEXT, amount INTEGER, description TEXT, expense_type TEXT, timestamp TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventory (id SERIAL PRIMARY KEY, user_id TEXT, product TEXT, quantity INTEGER, cost_price INTEGER, UNIQUE(user_id, product))''')
    # Fix old tables
    c.execute("ALTER TABLE inventory ADD COLUMN IF NOT EXISTS last_updated TIMESTAMP")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP")
    conn.commit(); conn.close()

def get_user(uid):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT business_name, language FROM users WHERE user_id=%s", (uid,))
    row = c.fetchone(); conn.close()
    return {'business_name': row[0], 'language': row[1]} if row else None

def create_user(uid):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO users (user_id, business_name, language, created_at) VALUES (%s,%s,%s,%s) ON CONFLICT (user_id) DO NOTHING",
              (uid, None, None, datetime.now(LAGOS)))
    conn.commit(); conn.close()

def update_business_name(uid, name):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET business_name=%s WHERE user_id=%s", (name, uid)); conn.commit(); conn.close()

def update_language(uid, lang):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET language=%s WHERE user_id=%s", (lang, uid)); conn.commit(); conn.close()

def save_sale(uid, amount, product, qty, pay):
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "INSERT INTO sales (user_id, amount, product, quantity, payment_method, timestamp) VALUES (%s, %s, %s, %s, %s, %s)",
        (uid, amount, product, qty, pay, datetime.now(LAGOS))
    )
    c.execute(
        "UPDATE inventory SET quantity = quantity - %s, last_updated=%s WHERE user_id=%s AND product=%s",
        (qty, datetime.now(LAGOS), uid, product)
    )
    conn.commit(); conn.close()

def save_expense(uid, amount, desc, typ):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO expenses (user_id, amount, description, expense_type, timestamp) VALUES (%s,%s,%s,%s,%s)",
              (uid, amount, desc, typ, datetime.now(LAGOS)))
    conn.commit(); conn.close()

def add_stock(uid, product, qty, cost):
    conn = get_conn(); c = conn.cursor()
    now = datetime.now(LAGOS)
    c.execute("""INSERT INTO inventory (user_id, product, quantity, cost_price, last_updated)
                 VALUES (%s,%s,%s,%s,%s)
                 ON CONFLICT (user_id, product)
                 DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                               cost_price = EXCLUDED.cost_price,
                               last_updated = EXCLUDED.last_updated""",
              (uid, product, qty, cost, now))
    conn.commit(); conn.close()

def get_stock(uid):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT product, quantity FROM inventory WHERE user_id=%s AND quantity>0 ORDER BY quantity DESC", (uid,))
    rows = c.fetchall(); conn.close()
    return rows

def get_period_sales(uid, period):
    conn = get_conn(); c = conn.cursor(); now = datetime.now(LAGOS)
    start = now.replace(hour=0,minute=0,second=0,microsecond=0) if period=='today' else now-timedelta(days=7)
    c.execute("SELECT COALESCE(SUM(amount),0) FROM sales WHERE user_id=%s AND timestamp>=%s", (uid, start))
    val = c.fetchone()[0]; conn.close(); return val

def get_period_expenses(uid, period, typ):
    conn = get_conn(); c = conn.cursor(); now = datetime.now(LAGOS)
    start = now.replace(hour=0,minute=0,second=0,microsecond=0) if period=='today' else now-timedelta(days=7)
    c.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE user_id=%s AND expense_type=%s AND timestamp>=%s", (uid, typ, start))
    val = c.fetchone()[0]; conn.close(); return val

def delete_last_entry(uid):
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM sales WHERE id IN (SELECT id FROM sales WHERE user_id=%s ORDER BY timestamp DESC LIMIT 1)", (uid,))
    deleted = c.rowcount; conn.commit(); conn.close(); return deleted>0
