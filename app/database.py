import sqlite3, os
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'sales.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, business_name TEXT, language TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY, user_id TEXT, amount INTEGER, product TEXT DEFAULT 'general', payment_method TEXT DEFAULT 'cash', timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY, user_id TEXT, amount INTEGER, description TEXT, type TEXT DEFAULT 'overhead', timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    # migrations
    try: c.execute("ALTER TABLE users ADD COLUMN language TEXT")
    except: pass
    try: c.execute("ALTER TABLE sales ADD COLUMN product TEXT DEFAULT 'general'")
    except: pass
    try: c.execute("ALTER TABLE sales ADD COLUMN payment_method TEXT DEFAULT 'cash'")
    except: pass
    try: c.execute("ALTER TABLE expenses ADD COLUMN type TEXT DEFAULT 'overhead'")
    except: pass
    conn.commit(); conn.close()

def get_user(uid):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    u = conn.execute("SELECT * FROM users WHERE user_id=?", (str(uid),)).fetchone()
    conn.close()
    return dict(u) if u else None

def create_user(uid):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (str(uid),))
    conn.commit(); conn.close()

def update_business_name(uid, name):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET business_name=? WHERE user_id=?", (name, str(uid)))
    conn.commit(); conn.close()

def update_language(uid, lang):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET language=? WHERE user_id=?", (lang, str(uid)))
    conn.commit(); conn.close()

def save_sale(uid, amt, prod='general', pay='cash'):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO sales (user_id, amount, product, payment_method) VALUES (?,?,?,?)", (str(uid), int(amt), prod.lower(), pay))
    conn.commit(); conn.close()

def save_expense(uid, amt, desc="", typ='overhead'):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO expenses (user_id, amount, description, type) VALUES (?,?,?,?)", (str(uid), int(amt), desc, typ))
    conn.commit(); conn.close()

def get_period_sales(uid, period='today', product=None, pay=None):
    q = {"today":"date(timestamp)=date('now','localtime')","yesterday":"date(timestamp)=date('now','-1 day','localtime')","week":"date(timestamp) >= date('now','-7 day','localtime')"}[period]
    sql = f"SELECT SUM(amount) FROM sales WHERE user_id=? AND {q}"; p=[str(uid)]
    if product: sql += " AND product=?"; p.append(product)
    if pay: sql += " AND payment_method=?"; p.append(pay)
    conn = sqlite3.connect(DB_PATH); t = conn.execute(sql, p).fetchone()[0] or 0; conn.close(); return t

def get_period_expenses(uid, period='today', typ=None):
    q = {"today":"date(timestamp)=date('now','localtime')","yesterday":"date(timestamp)=date('now','-1 day','localtime')","week":"date(timestamp) >= date('now','-7 day','localtime')"}[period]
    sql = f"SELECT SUM(amount) FROM expenses WHERE user_id=? AND {q}"; p=[str(uid)]
    if typ: sql += " AND type=?"; p.append(typ)
    conn = sqlite3.connect(DB_PATH); t = conn.execute(sql, p).fetchone()[0] or 0; conn.close(); return t

def get_best_product(uid, period='today'):
    q = {"today":"date(timestamp)=date('now','localtime')","week":"date(timestamp) >= date('now','-7 day','localtime')","yesterday":"date(timestamp)=date('now','-1 day','localtime')"}[period]
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute(f"SELECT product, SUM(amount) as total FROM sales WHERE user_id=? AND {q} GROUP BY product ORDER BY total DESC LIMIT 1", (str(uid),)).fetchone()
    conn.close(); return r[0].capitalize() if r else "None"

def delete_last_entry(uid):
    conn = sqlite3.connect(DB_PATH)
    # try sales first, then expenses
    sale = conn.execute("SELECT id FROM sales WHERE user_id=? ORDER BY id DESC LIMIT 1", (str(uid),)).fetchone()
    if sale:
        conn.execute("DELETE FROM sales WHERE id=?", (sale[0],))
        conn.commit(); conn.close(); return "sale"
    exp = conn.execute("SELECT id FROM expenses WHERE user_id=? ORDER BY id DESC LIMIT 1", (str(uid),)).fetchone()
    if exp:
        conn.execute("DELETE FROM expenses WHERE id=?", (exp[0],))
        conn.commit(); conn.close(); return "expense"
    conn.close(); return None

def get_last_sale(uid):
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute("SELECT amount, product FROM sales WHERE user_id=? ORDER BY id DESC LIMIT 1", (str(uid),)).fetchone()
    conn.close(); return r    