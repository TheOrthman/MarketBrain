import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'sales.db')

if not os.path.exists(DB_PATH):
    print("No database yet. Send a WhatsApp message first.")
    exit()

conn = sqlite3.connect(DB_PATH)

print("=== TODAY'S SALES ===")
sales_rows = list(conn.execute(
    "SELECT timestamp, amount FROM sales WHERE date(timestamp,'localtime') = date('now','localtime') ORDER BY id DESC"
))
for ts, amt in sales_rows:
    print(f"{ts} | +₦{amt:,}")

print("\n=== TODAY'S EXPENSES ===")
exp_rows = list(conn.execute(
    "SELECT timestamp, amount, description FROM expenses WHERE date(timestamp,'localtime') = date('now','localtime') ORDER BY id DESC"
))
for ts, amt, desc in exp_rows:
    print(f"{ts} | -₦{amt:,} | {desc}")

# Totals
total_sales = sum(r[1] for r in sales_rows)
total_exp = sum(r[1] for r in exp_rows)
net = total_sales - total_exp

print("\n--- SUMMARY ---")
print(f"Sales: ₦{total_sales:,}")
print(f"Expenses: ₦{total_exp:,}")
print(f"Net: ₦{net:,}")