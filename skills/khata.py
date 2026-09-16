"""
Khata (customer credit ledger) skill.

balance > 0  => customer owes the shop
balance < 0  => customer has paid in advance / overpaid

Guardrails: you cannot settle a khata for a customer who doesn't exist —
the agent must create the customer explicitly (or the credit tool does it
on first use) rather than silently inventing a ledger entry.
"""
from db.database import get_conn, transaction
from skills.inventory import SkillError


def _get_customer(name: str):
    conn = get_conn()
    return conn.execute("SELECT * FROM khata_customers WHERE lower(name) = lower(?)", (name,)).fetchone()


def get_or_create_customer(name: str, phone: str = None):
    row = _get_customer(name)
    if row:
        return dict(row)
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO khata_customers (name, phone, balance) VALUES (?, ?, 0)", (name, phone)
        )
    return {"id": cur.lastrowid, "name": name, "phone": phone, "balance": 0}


def khata_credit(customer_name: str, amount: float, bill_id: int = None, note: str = None, idempotency_key: str = None):
    if amount <= 0:
        raise SkillError("Credit amount must be positive.")
    if idempotency_key:
        conn = get_conn()
        dup = conn.execute("SELECT id FROM khata_transactions WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if dup:
            return khata_balance(customer_name) | {"idempotent_replay": True}

    customer = get_or_create_customer(customer_name)
    with transaction() as conn:
        conn.execute("UPDATE khata_customers SET balance = balance + ? WHERE id = ?", (amount, customer["id"]))
        conn.execute(
            "INSERT INTO khata_transactions (customer_id, txn_type, amount, bill_id, note, idempotency_key) "
            "VALUES (?, 'credit', ?, ?, ?, ?)",
            (customer["id"], amount, bill_id, note, idempotency_key),
        )
    return khata_balance(customer_name)


def khata_payment(customer_name: str, amount: float, idempotency_key: str = None):
    if amount <= 0:
        raise SkillError("Payment amount must be positive.")
    customer = _get_customer(customer_name)
    if not customer:
        raise SkillError(f"No khata account exists for '{customer_name}'. Cannot record a payment against nothing.")
    if idempotency_key:
        conn = get_conn()
        dup = conn.execute("SELECT id FROM khata_transactions WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if dup:
            return khata_balance(customer_name) | {"idempotent_replay": True}

    with transaction() as conn:
        conn.execute("UPDATE khata_customers SET balance = balance - ? WHERE id = ?", (amount, customer["id"]))
        conn.execute(
            "INSERT INTO khata_transactions (customer_id, txn_type, amount, idempotency_key) VALUES (?, 'payment', ?, ?)",
            (customer["id"], amount, idempotency_key),
        )
    return khata_balance(customer_name)


def khata_balance(customer_name: str):
    customer = _get_customer(customer_name)
    if not customer:
        raise SkillError(f"No khata account exists for '{customer_name}'.")
    return {"customer": customer["name"], "balance": customer["balance"]}


def khata_statement(customer_name: str, limit: int = 20):
    customer = _get_customer(customer_name)
    if not customer:
        raise SkillError(f"No khata account exists for '{customer_name}'.")
    conn = get_conn()
    rows = conn.execute(
        "SELECT txn_type, amount, note, created_at FROM khata_transactions WHERE customer_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (customer["id"], limit),
    ).fetchall()
    return {"customer": customer["name"], "balance": customer["balance"], "transactions": [dict(r) for r in rows]}


def list_khata_customers():
    conn = get_conn()
    rows = conn.execute("SELECT name, balance FROM khata_customers ORDER BY balance DESC").fetchall()
    return [dict(r) for r in rows]
