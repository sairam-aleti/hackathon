"""
Quick SQLite database inspector.
Run with: python3 db_inspect.py
"""

import sqlite3

conn = sqlite3.connect("allocation.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=" * 60)
print("ALLOCATION DATABASE SUMMARY (allocation.db)")
print("=" * 60)

tables = ["plants", "transport_duties", "orders", "capacity_events", "runs"]

for table in tables:
    count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"\n[Table: {table}] -> Total Records: {count}")
    
    # Print sample rows
    rows = cur.execute(f"SELECT * FROM {table} LIMIT 3").fetchall()
    for row in rows:
        print("  ", dict(row))

print("\n" + "=" * 60)
conn.close()
