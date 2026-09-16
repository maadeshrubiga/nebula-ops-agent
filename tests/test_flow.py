"""
Sanity test of the skills layer, independent of Telegram / the LLM.
Run with: python -m tests.test_flow
Exercises: stock-in, multi-turn bill + edit, oversell guard, GST math,
idempotent finalize, khata cycle, PDF invoice, PPTX deck, preferences.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["NEBULA_DB_PATH"] = os.path.join(os.path.dirname(__file__), "test_store.db")
for suffix in ("", "-wal", "-shm"):
    p = os.environ["NEBULA_DB_PATH"] + suffix
    if os.path.exists(p):
        os.remove(p)

from db.database import init_db, seed_demo_products
from skills import inventory, billing, khata, analytics, preferences, documents
from skills.inventory import SkillError


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    assert cond, label


def run():
    init_db()
    seed_demo_products()

    # --- receive stock ---
    r = inventory.receive_stock("Maggi 70g", 50, cost_price=12, sell_price=14)
    check("stock-in updates quantity", r["new_quantity"] >= 150)

    # --- add a genuinely new product ---
    p = inventory.add_product("Britannia Bourbon 150g", "packet", 18, 20, 30)
    check("new product added", p["name"] == "Britannia Bourbon 150g")


def run_duplicate_guard():
    try:
        inventory.add_product("Amul Butter 100g", "packet", 12, 48, 62)
        check("duplicate product should raise", False)
    except SkillError:
        check("duplicate product correctly rejected", True)


def run_billing_flow():
    bill = billing.start_bill(customer_name="Ramesh", chat_id=1)
    bid = bill["bill_id"]
    billing.add_bill_item(bid, "Sugar (loose)", 2)
    billing.add_bill_item(bid, "Aashirvaad Atta 5kg", 1)
    billing.add_bill_item(bid, "Maggi 70g", 4)
    billing.add_bill_item(bid, "Amul Butter 100g", 1)

    # edit mid-build: drop butter, change maggi qty
    billing.remove_bill_item(bid, "Amul Butter 100g")
    billing.update_bill_item_qty(bid, "Maggi 70g", 6)

    state = billing.get_bill(bid)
    check("butter removed", all(i["product_name"] != "Amul Butter 100g" for i in state["items"]))
    check("maggi qty updated to 6", any(i["product_name"] == "Maggi 70g" and i["qty"] == 6 for i in state["items"]))
    check("GST breakup present", state["cgst_total"] > 0 and state["sgst_total"] == state["cgst_total"])

    billing.set_bill_payment(bid, "upi")
    result = billing.finalize_bill(bid, finalize_token=f"test-token-{bid}")
    check("bill finalized", result["status"] == "finalized")

    # idempotent replay of the SAME token must not double-decrement stock
    stock_before = inventory.get_stock("Maggi 70g")["quantity"]
    replay = billing.finalize_bill(bid, finalize_token=f"test-token-{bid}")
    stock_after = inventory.get_stock("Maggi 70g")["quantity"]
    check("idempotent finalize replay flagged", replay.get("idempotent_replay") is True)
    check("idempotent finalize does not double-decrement stock", stock_before == stock_after)

    return bid


def run_oversell_guard():
    bill = billing.start_bill(customer_name="Test Oversell")
    bid = bill["bill_id"]
    stock = inventory.get_stock("Tata Salt 1kg")["quantity"]
    try:
        billing.add_bill_item(bid, "Tata Salt 1kg", stock + 1000)
        check("oversell should have been blocked", False)
    except SkillError:
        check("oversell blocked at add_bill_item", True)


def run_below_cost_guard():
    bill = billing.start_bill()
    bid = bill["bill_id"]
    product = inventory.find_product("Tata Salt 1kg")
    try:
        billing.add_bill_item(bid, "Tata Salt 1kg", 1, unit_price=product["cost_price"] - 1)
        check("below-cost sale should have been blocked", False)
    except SkillError:
        check("below-cost sale blocked", True)


def run_khata_cycle():
    khata.khata_credit("Ramesh", 500, note="manual credit")
    bal = khata.khata_balance("Ramesh")
    check("khata credit recorded", bal["balance"] >= 500)
    khata.khata_payment("Ramesh", 300)
    bal2 = khata.khata_balance("Ramesh")
    check("khata payment reduces balance by 300", abs(bal["balance"] - bal2["balance"] - 300) < 1e-6)
    try:
        khata.khata_payment("NoSuchPerson", 100)
        check("payment against nonexistent khata should fail", False)
    except SkillError:
        check("payment against nonexistent khata correctly refused", True)


def run_preferences():
    preferences.set_preference("default_payment_mode", "upi")
    prefs = preferences.get_all_preferences()
    check("preference persisted", prefs.get("default_payment_mode") == "upi")
    preferences.set_shop_info(name="Test Kirana", gstin="29TESTGSTIN1Z5")
    shop = preferences.get_shop_info()
    check("shop info persisted", shop["name"] == "Test Kirana")


def run_documents(bill_id):
    inv = documents.generate_invoice_pdf(bill_id)
    check("invoice PDF created", os.path.exists(inv["file_path"]) and os.path.getsize(inv["file_path"]) > 0)

    from datetime import date
    today = date.today().isoformat()
    deck = documents.generate_analysis_deck(today, today)
    check("analysis PPTX created", os.path.exists(deck["file_path"]) and os.path.getsize(deck["file_path"]) > 0)


if __name__ == "__main__":
    run()
    run_duplicate_guard()
    bid = run_billing_flow()
    run_oversell_guard()
    run_below_cost_guard()
    run_khata_cycle()
    run_preferences()
    run_documents(bid)
    print("\nALL CHECKS PASSED")
