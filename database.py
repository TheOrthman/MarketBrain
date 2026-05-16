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
    c.execute('''CREATE TABLE IF NOT EXISTS sales (id SERIAL PRIMARY KEY, user_id TEXT, amount INTEGER, product TEXT, payment_method TEXT, timestamp TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (id SERIAL PRIMARY KEY, user_id TEXT, amount INTEGER, description TEXT, expense_type TEXT, timestamp TIMESTAMP)''')
    conn.commit(); conn.close()

def get_user(uid):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT business_name, language FROM users WHERE user_id=%s", (uid,))
    row = c.fetchone(); conn.close()
    return {'business_name': row[0], 'language': row[1]} if row else None

def create_user(uid):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO users VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", (uid, None, None, datetime.now(LAGOS)))
    conn.commit(); conn.close()

def update_business_name(uid, name):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET business_name=%s WHERE user_id=%s", (name, uid))
    conn.commit(); conn.close()

def update_language(uid, lang):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET language=%s WHERE user_id=%s", (lang, uid))
    conn.commit(); conn.close()

def save_sale(uid, amount, product, pay):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO sales (user_id,amount,product,payment_method,timestamp) VALUES (%s,%s,%s,%s,%s)", (uid, amount, product, pay, datetime.now(LAGOS)))
    conn.commit(); conn.close()

def save_expense(uid, amount, desc, typ):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO expenses (user_id,amount,description,expense_type,timestamp) VALUES (%s,%s,%s,%s,%s)", (uid, amount, desc, typ, datetime.now(LAGOS)))
    conn.commit(); conn.close()

def get_period_sales(uid, period, pay=None):
    conn = get_conn(); c = conn.cursor(); now = datetime.now(LAGOS)
    if period=='today': start = now.replace(hour=0,minute=0)
    elif period=='yesterday': start = (now-timedelta(days=1)).replace(hour=0,minute=0); end = now.replace(hour=0,minute=0)
    else: start = now-timedelta(days=7)
    if period=='yesterday': q="SELECT COALESCE(SUM(amount),0) FROM sales WHERE user_id=%s AND timestamp>=%s AND timestamp<%s"; params=[uid,start,end]
    else: q="SELECT COALESCE(SUM(amount),0) FROM sales WHERE user_id=%s AND timestamp>=%s"; params=[uid,start]
    if pay: q+=" AND payment_method=%s"; params.append(pay)
    c.execute(q, tuple(params)); val=c.fetchone()[0]; conn.close(); return val

def get_period_expenses(uid, period, typ):
    conn = get_conn(); c = conn.cursor(); now=datetime.now(LAGOS)
    if period=='today': start=now.replace(hour=0,minute=0)
    elif period=='yesterday': start=(now-timedelta(days=1)).replace(hour=0,minute=0); end=now.replace(hour=0,minute=0)
    else: start=now-timedelta(days=7)
    if period=='yesterday': c.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE user_id=%s AND expense_type=%s AND timestamp>=%s AND timestamp<%s",(uid,typ,start,end))
    else: c.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE user_id=%s AND expense_type=%s AND timestamp>=%s",(uid,typ,start))
    val=c.fetchone()[0]; conn.close(); return val

def get_best_product(uid, period):
    conn=get_conn(); c=conn.cursor(); start=datetime.now(LAGOS)-timedelta(days=7)
    c.execute("SELECT product, SUM(amount) FROM sales WHERE user_id=%s AND timestamp>=%s GROUP BY product ORDER BY SUM(amount) DESC LIMIT 1",(uid,start))
    row=c.fetchone(); conn.close(); return row[0] if row else 'none'

def delete_last_entry(uid):
    conn=get_conn(); c=conn.cursor()
    c.execute("DELETE FROM sales WHERE id IN (SELECT id FROM sales WHERE user_id=%s ORDER BY timestamp DESC LIMIT 1)",(uid,))
    if c.rowcount==0: c.execute("DELETE FROM expenses WHERE id IN (SELECT id FROM expenses WHERE user_id=%s ORDER BY timestamp DESC LIMIT 1)",(uid,))
    conn.commit(); conn.close(); return c.rowcount>0
