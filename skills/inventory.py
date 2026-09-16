"""
Inventory skill: catalog + stock-in + stock lookups.

These are the tools the agent calls for grounding — the model is never
allowed to state a price, GST slab, or stock count from its own memory.
Every fact-bearing tool below returns exact DB values.
"""
from db.database import get_conn, transaction


class SkillError(Exception):
    """Raised for business-rule violations; caught by the orchestrator and
    surfaced to the model as a tool_result error so it can explain/ask, not guess."""


def _row_to_dict(row):
    return dict(row) if row else None


def find_product(name_query: str):
    """Case-insensitive exact-then-fuzzy match. Returns the product row or None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM products WHERE lower(name) = lower(?) AND is_active = 1", (name_query,)
    ).fetchone()
    if row:
        return row
    rows = conn.execute(
        "SELECT * FROM products WHERE is_active = 1 AND lower(name) LIKE lower(?)",
        (f"%{name_query}%",),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]
    return None  # 0 or >1 matches — caller (agent) should disambiguate, not guess


def search_products(query: str, limit: int = 8):
    """Used by the agent to resolve ambiguous references, e.g. 'atta' -> multiple SKUs."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM products WHERE is_active = 1 AND lower(name) LIKE lower(?) ORDER BY name LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def add_product(name: str, unit: str, gst_rate: float, cost_price: float, sell_price: float,
                 is_loose: bool = False, hsn_code: str = None, quantity: float = 0,
                 reorder_level: float = 0):
    conn = get_conn()
    existing = conn.execute("SELECT id FROM products WHERE lower(name) = lower(?)", (name,)).fetchone()
    if existing:
        raise SkillError(f"Product '{name}' already exists (id={existing['id']}). Use receive_stock to add quantity.")
    if gst_rate not in (0, 5, 12, 18, 28):
        raise SkillError(f"GST rate {gst_rate}% is not a standard slab (0/5/12/18/28). Confirm with the owner.")
    with transaction() as conn:
        cur = conn.execute(
            """INSERT INTO products (name, unit, is_loose, hsn_code, gst_rate, cost_price, sell_price, quantity, reorder_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, unit, int(is_loose), hsn_code, gst_rate, cost_price, sell_price, quantity, reorder_level),
        )
        pid = cur.lastrowid
        if quantity:
            conn.execute(
                "INSERT INTO stock_transactions (product_id, change_qty, txn_type, cost_price_at_time) VALUES (?, ?, 'stock_in', ?)",
                (pid, quantity, cost_price),
            )
    return {"product_id": pid, "name": name, "message": f"Added new product '{name}'."}


def receive_stock(product_name: str, quantity: float, cost_price: float = None, sell_price: float = None):
    """Stock-in. Updates cost_price/sell_price only if explicitly provided (a new consignment can
    arrive at a different cost without changing the shelf price the owner already set)."""
    if quantity <= 0:
        raise SkillError("Stock-in quantity must be positive.")
    product = find_product(product_name)
    if not product:
        matches = search_products(product_name)
        if matches:
            names = ", ".join(m["name"] for m in matches)
            raise SkillError(f"'{product_name}' is ambiguous or not found exactly. Did you mean: {names}?")
        raise SkillError(f"No product named '{product_name}' exists. Add it first with add_product.")

    with transaction() as conn:
        sets = ["quantity = quantity + ?", "updated_at = CURRENT_TIMESTAMP"]
        params = [quantity]
        if cost_price is not None:
            sets.append("cost_price = ?")
            params.append(cost_price)
        if sell_price is not None:
            sets.append("sell_price = ?")
            params.append(sell_price)
        params.append(product["id"])
        conn.execute(f"UPDATE products SET {', '.join(sets)} WHERE id = ?", params)
        conn.execute(
            "INSERT INTO stock_transactions (product_id, change_qty, txn_type, cost_price_at_time) VALUES (?, ?, 'stock_in', ?)",
            (product["id"], quantity, cost_price if cost_price is not None else product["cost_price"]),
        )
        new_row = conn.execute("SELECT * FROM products WHERE id = ?", (product["id"],)).fetchone()
    return {
        "product": new_row["name"],
        "received": quantity,
        "new_quantity": new_row["quantity"],
        "cost_price": new_row["cost_price"],
        "sell_price": new_row["sell_price"],
    }


def get_stock(product_name: str):
    product = find_product(product_name)
    if not product:
        matches = search_products(product_name)
        if matches:
            return {"ambiguous": True, "candidates": [m["name"] for m in matches]}
        raise SkillError(f"No product named '{product_name}'.")
    return {
        "product": product["name"],
        "quantity": product["quantity"],
        "unit": product["unit"],
        "reorder_level": product["reorder_level"],
        "sell_price": product["sell_price"],
        "gst_rate": product["gst_rate"],
    }


def list_low_stock():
    conn = get_conn()
    rows = conn.execute(
        "SELECT name, quantity, unit, reorder_level FROM products WHERE is_active = 1 AND quantity <= reorder_level ORDER BY quantity ASC"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_all_products():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM products WHERE is_active = 1 ORDER BY name").fetchall()
    return [_row_to_dict(r) for r in rows]
