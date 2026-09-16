"""
Billing skill.

Key design points (the "hard parts" from the brief):

- Multi-turn bills: a bill is a `draft` row plus `bill_items` rows. The agent
  calls start_bill / add_bill_item / remove_bill_item / update_bill_item_qty
  freely across turns; nothing touches `products.quantity` until finalize.

- Oversell guard lives here, not in the prompt: add_bill_item does a soft
  check against (stock - already-reserved-in-this-draft) so the owner gets
  fast feedback, but the HARD guard is the conditional UPDATE inside
  finalize_bill: `UPDATE products SET quantity = quantity - ? WHERE id = ?
  AND quantity >= ?`. If that affects 0 rows, we roll back the whole
  finalize transaction and report oversell — this is safe even if two bills
  race, because both run inside BEGIN IMMEDIATE transactions that SQLite
  serializes.

- Idempotency: finalize_bill takes a `finalize_token` supplied by the
  orchestrator (derived from the Telegram update_id / a stable client
  token). It's a UNIQUE column on `bills`. If the same token is replayed,
  we detect the bill is already finalized and return the cached result
  instead of decrementing stock a second time.

- GST: CGST + SGST split assuming intra-state, each = gst_rate / 2 applied
  to the taxable value, rounded to paise (2 decimals) per line item, then
  totals summed from the rounded line items (this is how real POS/GST
  invoices avoid rounding disputes).
"""
from db.database import get_conn, transaction
from skills.inventory import find_product, search_products, SkillError


def _round2(x):
    return round(x + 1e-9, 2)


def start_bill(customer_name: str = None, chat_id: int = None):
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO bills (chat_id, customer_name, status) VALUES (?, ?, 'draft')",
            (chat_id, customer_name),
        )
    return {"bill_id": cur.lastrowid, "status": "draft"}


def _get_draft_bill(bill_id: int):
    conn = get_conn()
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        raise SkillError(f"No bill with id {bill_id}.")
    if bill["status"] != "draft":
        raise SkillError(f"Bill {bill_id} is already {bill['status']}; cannot modify it.")
    return bill


def _reserved_qty_in_draft(bill_id: int, product_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(SUM(qty),0) AS q FROM bill_items WHERE bill_id = ? AND product_id = ?",
        (bill_id, product_id),
    ).fetchone()
    return row["q"]


def add_bill_item(bill_id: int, product_name: str, qty: float, unit_price: float = None):
    if qty <= 0:
        raise SkillError("Quantity must be positive.")
    _get_draft_bill(bill_id)
    product = find_product(product_name)
    if not product:
        matches = search_products(product_name)
        if matches:
            names = ", ".join(m["name"] for m in matches)
            raise SkillError(f"'{product_name}' is ambiguous. Did you mean: {names}?")
        raise SkillError(f"No product named '{product_name}' in the catalog. Cannot invent a price.")

    price = unit_price if unit_price is not None else product["sell_price"]
    if price < product["cost_price"]:
        raise SkillError(
            f"Refusing: selling {product['name']} at ₹{price} is below cost price ₹{product['cost_price']}. "
            f"Confirm explicitly with a manual override if this is intentional."
        )

    already_reserved = _reserved_qty_in_draft(bill_id, product["id"])
    available = product["quantity"] - already_reserved
    if qty > available:
        raise SkillError(
            f"Oversell blocked: only {available} {product['unit']} of {product['name']} available "
            f"(stock {product['quantity']}, already {already_reserved} in this bill)."
        )

    gst_rate = product["gst_rate"]
    taxable_value = _round2(price * qty)
    cgst = _round2(taxable_value * (gst_rate / 2) / 100)
    sgst = _round2(taxable_value * (gst_rate / 2) / 100)
    line_total = _round2(taxable_value + cgst + sgst)

    with transaction() as conn:
        conn.execute(
            """INSERT INTO bill_items
               (bill_id, product_id, product_name, qty, unit, unit_price, gst_rate,
                taxable_value, cgst_amount, sgst_amount, line_total)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (bill_id, product["id"], product["name"], qty, product["unit"], price, gst_rate,
             taxable_value, cgst, sgst, line_total),
        )
    return get_bill(bill_id)


def remove_bill_item(bill_id: int, product_name: str):
    _get_draft_bill(bill_id)
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM bill_items WHERE bill_id = ? AND lower(product_name) = lower(?) ORDER BY id DESC LIMIT 1",
        (bill_id, product_name),
    ).fetchone()
    if not row:
        raise SkillError(f"'{product_name}' is not on bill {bill_id}.")
    with transaction() as conn:
        conn.execute("DELETE FROM bill_items WHERE id = ?", (row["id"],))
    return get_bill(bill_id)


def update_bill_item_qty(bill_id: int, product_name: str, new_qty: float):
    if new_qty <= 0:
        return remove_bill_item(bill_id, product_name)
    _get_draft_bill(bill_id)
    conn = get_conn()
    item = conn.execute(
        "SELECT * FROM bill_items WHERE bill_id = ? AND lower(product_name) = lower(?) ORDER BY id DESC LIMIT 1",
        (bill_id, product_name),
    ).fetchone()
    if not item:
        raise SkillError(f"'{product_name}' is not on bill {bill_id}. Use add_bill_item instead.")

    product = find_product(item["product_name"])
    other_reserved = _reserved_qty_in_draft(bill_id, product["id"]) - item["qty"]
    available = product["quantity"] - other_reserved
    if new_qty > available:
        raise SkillError(f"Oversell blocked: only {available} {product['unit']} of {product['name']} available.")

    gst_rate = item["gst_rate"]
    price = item["unit_price"]
    taxable_value = _round2(price * new_qty)
    cgst = _round2(taxable_value * (gst_rate / 2) / 100)
    sgst = _round2(taxable_value * (gst_rate / 2) / 100)
    line_total = _round2(taxable_value + cgst + sgst)
    with transaction() as conn:
        conn.execute(
            "UPDATE bill_items SET qty=?, taxable_value=?, cgst_amount=?, sgst_amount=?, line_total=? WHERE id=?",
            (new_qty, taxable_value, cgst, sgst, line_total, item["id"]),
        )
    return get_bill(bill_id)


def get_bill(bill_id: int):
    conn = get_conn()
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        raise SkillError(f"No bill with id {bill_id}.")
    items = conn.execute("SELECT * FROM bill_items WHERE bill_id = ?", (bill_id,)).fetchall()
    subtotal = _round2(sum(i["taxable_value"] for i in items))
    cgst_total = _round2(sum(i["cgst_amount"] for i in items))
    sgst_total = _round2(sum(i["sgst_amount"] for i in items))
    grand_total = _round2(subtotal + cgst_total + sgst_total)
    return {
        "bill_id": bill_id,
        "status": bill["status"],
        "customer_name": bill["customer_name"],
        "payment_mode": bill["payment_mode"],
        "items": [dict(i) for i in items],
        "subtotal": subtotal,
        "cgst_total": cgst_total,
        "sgst_total": sgst_total,
        "grand_total": grand_total,
    }


def set_bill_payment(bill_id: int, payment_mode: str, payment_ref: str = None, customer_name: str = None):
    _get_draft_bill(bill_id)
    payment_mode = payment_mode.lower()
    if payment_mode not in ("cash", "upi", "card", "khata"):
        raise SkillError("payment_mode must be one of: cash, upi, card, khata.")
    if payment_mode == "khata" and not customer_name:
        raise SkillError("khata payment requires a customer_name to put it on their credit.")
    with transaction() as conn:
        conn.execute(
            "UPDATE bills SET payment_mode=?, payment_ref=?, customer_name = COALESCE(?, customer_name) WHERE id=?",
            (payment_mode, payment_ref, customer_name, bill_id),
        )
    return get_bill(bill_id)


def finalize_bill(bill_id: int, finalize_token: str):
    """
    Idempotent, atomic finalize.
    - `finalize_token` should be stable across retries of the *same* logical
      request (the orchestrator derives it from the Telegram update_id).
    - If a bill with this token is already finalized, we return the stored
      result WITHOUT touching stock again.
    """
    conn = get_conn()
    existing = conn.execute("SELECT * FROM bills WHERE finalize_token = ?", (finalize_token,)).fetchone()
    if existing and existing["status"] == "finalized":
        return get_bill(existing["id"]) | {"idempotent_replay": True}

    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        raise SkillError(f"No bill with id {bill_id}.")
    if bill["status"] == "finalized":
        return get_bill(bill_id) | {"idempotent_replay": True}
    if bill["status"] == "cancelled":
        raise SkillError(f"Bill {bill_id} was cancelled.")

    items = conn.execute("SELECT * FROM bill_items WHERE bill_id = ?", (bill_id,)).fetchall()
    if not items:
        raise SkillError("Cannot finalize an empty bill.")
    if not bill["payment_mode"]:
        raise SkillError("No payment mode set. Ask cash/UPI/card/khata before finalizing.")

    with transaction() as conn:
        # Hard oversell guard: conditional UPDATE, atomic per item, inside one transaction.
        for item in items:
            cur = conn.execute(
                "UPDATE products SET quantity = quantity - ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND quantity >= ?",
                (item["qty"], item["product_id"], item["qty"]),
            )
            if cur.rowcount == 0:
                # rolls back the whole transaction — no partial stock decrement
                raise SkillError(
                    f"Oversell blocked at finalize: not enough stock left for {item['product_name']}. "
                    f"Someone else may have sold it first. Nothing was billed."
                )
            conn.execute(
                "INSERT INTO stock_transactions (product_id, change_qty, txn_type, ref_type, ref_id) "
                "VALUES (?, ?, 'sale', 'bill', ?)",
                (item["product_id"], -item["qty"], bill_id),
            )

        subtotal = _round2(sum(i["taxable_value"] for i in items))
        cgst_total = _round2(sum(i["cgst_amount"] for i in items))
        sgst_total = _round2(sum(i["sgst_amount"] for i in items))
        grand_total = _round2(subtotal + cgst_total + sgst_total)

        conn.execute(
            """UPDATE bills SET status='finalized', finalize_token=?, subtotal=?, cgst_total=?,
               sgst_total=?, grand_total=?, finalized_at=CURRENT_TIMESTAMP WHERE id=?""",
            (finalize_token, subtotal, cgst_total, sgst_total, grand_total, bill_id),
        )

        # khata payment mode: push the total onto the customer's credit ledger
        if bill["payment_mode"] == "khata":
            from skills import khata
            khata.khata_credit(
                bill["customer_name"], grand_total, bill_id=bill_id,
                note=f"Bill #{bill_id}", idempotency_key=f"finalize:{finalize_token}",
            )

    return get_bill(bill_id)


def cancel_bill(bill_id: int):
    _get_draft_bill(bill_id)
    with transaction() as conn:
        conn.execute("UPDATE bills SET status='cancelled' WHERE id=?", (bill_id,))
    return {"bill_id": bill_id, "status": "cancelled"}
