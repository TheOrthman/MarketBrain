import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
import pytz

DATABASE_URL = os.getenv("DATABASE_URL")
LAGOS = pytz.timezone('Africa/Lagos')

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, business_name TEXT, language TEXT DEFAULT 'en', created_at TIMESTAMP DEFAULT NOW())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS sales (
        id SERIAL PRIMARY KEY, user_id TEXT, amount INTEGER, product TEXT,
        payment_method TEXT, quantity INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT NOW())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS expenses (
        id SERIAL PRIMARY KEY, user_id TEXT, amount INTEGER, description TEXT,
        type TEXT, created_at TIMESTAMP DEFAULT NOW())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS inventory (
        id SERIAL PRIMARY KEY, user_id TEXT, product TEXT, quantity INTEGER DEFAULT 0,
        cost_price INTEGER, low_threshold INTEGER DEFAULT 5, updated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(user_id, product))""")
    conn.commit(); cur.close(); conn.close()

def get_user(user_id):
    conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM users WHERE id=%s", (user_id,)); user = cur.fetchone()
    cur.close(); conn.close(); return user

def create_user(user_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO users (id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
    conn.commit(); cur.close(); conn.close()

def update_business_name(user_id, name):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE users SET business_name=%s WHERE id=%s", (name, user_id))
    conn.commit(); cur.close(); conn.close()

def update_language(user_id, lang):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE users SET language=%s WHERE id=%s", (lang, user_id))
    conn.commit(); cur.close(); conn.close()

def save_sale(user_id, amount, product, payment, quantity=1):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO sales (user_id, amount, product, payment_method, quantity) VALUES (%s,%s,%s,%s,%s)",
                (user_id, amount, product, payment, quantity))
    conn.commit(); cur.close(); conn.close()

def save_expense(user_id, amount, desc, typ):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO expenses (user_id, amount, description, type) VALUES (%s,%s,%s,%s)",
                (user_id, amount, desc, typ))
    conn.commit(); cur.close(); conn.close()

def add_stock(user_id, product, qty, cost):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO inventory (user_id, product, quantity, cost_price, updated_at)
        VALUES (%s,%s,%s,%s,NOW())
        ON CONFLICT (user_id, product) DO UPDATE SET
        quantity = inventory.quantity + EXCLUDED.quantity,
        cost_price = EXCLUDED.cost_price, updated_at=NOW()""",
        (user_id, product.lower(), qty, cost))
    conn.commit(); cur.close(); conn.close()

def remove_stock(user_id, product, qty):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE inventory SET quantity = GREATEST(quantity - %s,0), updated_at=NOW() WHERE user_id=%s AND product=%s RETURNING quantity",
                (qty, user_id, product.lower()))
    res = cur.fetchone(); conn.commit(); cur.close(); conn.close()
    return res[0] if res else 0

def get_stock(user_id, product):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT quantity FROM inventory WHERE user_id=%s AND product=%s", (user_id, product.lower()))
    row = cur.fetchone(); cur.close(); conn.close(); return row[0] if row else 0

def get_all_stock(user_id):
    conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT product, quantity FROM inventory WHERE user_id=%s ORDER BY quantity", (user_id,))
    rows = cur.fetchall(); cur.close(); conn.close(); return rows

def get_period_sales(user_id, period):
    conn = get_conn(); cur = conn.cursor()
    now = datetime.now(LAGOS)
    if period == 'today': start = now.replace(hour=0,minute=0)
    elif period == 'yesterday': start = (now - timedelta(days=1)).replace(hour=0,minute=0)
    else: start = now - timedelta(days=7)
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM sales WHERE user_id=%s AND created_at >= %s", (user_id, start))
    total = cur.fetchone()[0]; cur.close(); conn.close(); return total

def get_period_expenses(user_id, period, typ):
    conn = get_conn(); cur = conn.cursor()
    now = datetime.now(LAGOS)
    if period == 'today': start = now.replace(hour=0,minute=0)
    elif period == 'yesterday': start = (now - timedelta(days=1)).replace(hour=0,minute=0)
    else: start = now - timedelta(days=7)
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE user_id=%s AND type=%s AND created_at >= %s", (user_id, typ, start))
    total = cur.fetchone()[0]; cur.close(); conn.close(); return total

def delete_last_entry(user_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM sales WHERE id=(SELECT id FROM sales WHERE user_id=%s ORDER BY created_at DESC LIMIT 1)", (user_id,))
    conn.commit(); cur.close(); conn.close(); return True
