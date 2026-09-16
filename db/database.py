"""
Connection helper for the kirana store DB.

Design notes:
- SQLite in WAL mode. WAL lets one writer + many readers proceed concurrently
  without blocking, which is what we need for "check stock" queries to keep
  working while a bill is being finalized.
- Every write that touches `products.quantity` goes through a single
  connection-scoped transaction using `BEGIN IMMEDIATE`, which takes a
  write lock up front instead of optimistically and failing later. Combined
  with the CHECK(quantity >= 0) constraint and a conditional UPDATE
  (`WHERE quantity >= ?`), two concurrent sales of the same low-stock item
  cannot both succeed — the second one's UPDATE affects 0 rows and the
  caller sees that and reports oversell.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.environ.get("NEBULA_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "nebula_store.db"))
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

_local = threading.local()
_write_lock = threading.Lock()  # extra belt-and-braces guard for SQLite's single-writer model


def get_conn():
    """Thread-local connection so each bot handler/thread gets its own."""
    if not hasattr(_local, "conn"):
        conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)  # autocommit; we manage BEGIN explicitly
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        _local.conn = conn
    return _local.conn


@contextmanager
def transaction():
    """
    Explicit write transaction. Use for any operation that must be atomic
    (stock decrement, bill finalize, khata settle).
    """
    conn = get_conn()
    with _write_lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def init_db():
    conn = get_conn()
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.execute(
        "INSERT OR IGNORE INTO shop_info (id, name, gstin, address, phone) VALUES (1, ?, ?, ?, ?)",
        ("My Kirana Store", "29ABCDE1234F1Z5", "Coimbatore, TN", "9999999999"),
    )


def seed_demo_products():
    """Realistic Indian kirana SKUs, per the assignment brief. Safe to call repeatedly (INSERT OR IGNORE)."""
    conn = get_conn()
    products = [
        # name, unit, is_loose, hsn, gst_rate, cost, sell, qty, reorder_level
        ("Aashirvaad Atta 5kg", "packet", 0, "1101", 5, 210, 249, 40, 10),
        ("Tata Salt 1kg", "packet", 0, "2501", 5, 18, 24, 60, 15),
        ("Amul Butter 100g", "packet", 0, "0405", 12, 48, 62, 30, 10),
        ("Fortune Sunflower Oil 1L", "packet", 0, "1512", 5, 118, 149, 25, 8),
        ("Maggi 70g", "packet", 0, "1902", 12, 12, 14, 100, 20),
        ("Parle-G", "packet", 0, "1905", 18, 8, 10, 150, 30),
        ("Surf Excel 1kg", "packet", 0, "3402", 18, 95, 125, 20, 5),
        ("Sugar (loose)", "kg", 1, "1701", 0, 38, 45, 80, 15),
        ("Rice (loose)", "kg", 1, "1006", 0, 32, 40, 100, 20),
        ("Toor Dal (loose)", "kg", 1, "0713", 0, 95, 118, 50, 10),
    ]
    for p in products:
        conn.execute(
            """INSERT OR IGNORE INTO products
               (name, unit, is_loose, hsn_code, gst_rate, cost_price, sell_price, quantity, reorder_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            p,
        )


if __name__ == "__main__":
    init_db()
    seed_demo_products()
    print(f"Initialized DB at {os.path.abspath(DB_PATH)} with demo SKUs.")
