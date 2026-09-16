"""
Preferences skill = the durable memory layer.

Anything the owner says as a standing instruction ("always assume UPI unless
I say cash", "default atta = Aashirvaad 5kg", shop name/GSTIN for invoices)
is written here, in SQLite — not in the chat transcript. The orchestrator
loads all current preferences into the system prompt at the START of every
turn (even after /new), so this is what makes memory survive a fresh chat.
"""
from db.database import get_conn, transaction


def set_preference(key: str, value: str):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (key, value),
        )
    return {"key": key, "value": value, "message": f"Remembered: {key} = {value}"}


def get_preference(key: str, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def get_all_preferences():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM preferences ORDER BY key").fetchall()
    return {r["key"]: r["value"] for r in rows}


def set_shop_info(name: str = None, gstin: str = None, address: str = None, phone: str = None):
    conn = get_conn()
    current = conn.execute("SELECT * FROM shop_info WHERE id=1").fetchone()
    with transaction() as conn:
        conn.execute(
            "UPDATE shop_info SET name=COALESCE(?,name), gstin=COALESCE(?,gstin), "
            "address=COALESCE(?,address), phone=COALESCE(?,phone) WHERE id=1",
            (name, gstin, address, phone),
        )
    return get_shop_info()


def get_shop_info():
    conn = get_conn()
    row = conn.execute("SELECT * FROM shop_info WHERE id=1").fetchone()
    return dict(row) if row else {}
