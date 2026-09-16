"""
The tool surface the model orchestrates over. Kept intentionally thin and
composable — no single tool does more than one clear job, and no tool
contains "figure out what the owner meant" logic; that reasoning stays with
the model, which then calls the right thin tool.
"""
from skills import inventory, billing, khata, analytics, preferences, documents
from skills.inventory import SkillError

TOOLS = [
    # ---------- Inventory ----------
    {
        "name": "search_products",
        "description": "Search the product catalog by partial name. Use this whenever a product reference is ambiguous (e.g. 'atta' could match several SKUs) before asking the owner to clarify, or before assuming a product doesn't exist.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "add_product",
        "description": "Add a brand-new SKU to the catalog. Fails if the product already exists — use receive_stock for existing products.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "unit": {"type": "string", "enum": ["kg", "g", "litre", "ml", "packet", "dozen", "piece"]},
                "is_loose": {"type": "boolean", "default": False},
                "hsn_code": {"type": "string"},
                "gst_rate": {"type": "number", "description": "GST slab percent: 0, 5, 12, 18, or 28"},
                "cost_price": {"type": "number"},
                "sell_price": {"type": "number"},
                "quantity": {"type": "number", "default": 0},
                "reorder_level": {"type": "number", "default": 0},
            },
            "required": ["name", "unit", "gst_rate", "cost_price", "sell_price"],
        },
    },
    {
        "name": "receive_stock",
        "description": "Record incoming stock for an existing product (a fresh consignment arriving). Can optionally update cost/sell price if the new consignment changed them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_name": {"type": "string"},
                "quantity": {"type": "number"},
                "cost_price": {"type": "number"},
                "sell_price": {"type": "number"},
            },
            "required": ["product_name", "quantity"],
        },
    },
    {
        "name": "get_stock",
        "description": "Look up current quantity, unit, price and GST rate for one product.",
        "input_schema": {"type": "object", "properties": {"product_name": {"type": "string"}}, "required": ["product_name"]},
    },
    {
        "name": "list_low_stock",
        "description": "List all products at or below their reorder level — answers 'what's running out?'.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_all_products",
        "description": "List the full product catalog with current stock and prices.",
        "input_schema": {"type": "object", "properties": {}},
    },

    # ---------- Billing ----------
    {
        "name": "start_bill",
        "description": "Start a new draft bill. Returns a bill_id to use for all subsequent add/remove/finalize calls in this billing session.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_name": {"type": "string"}, "chat_id": {"type": "integer"}},
            "required": [],
        },
    },
    {
        "name": "add_bill_item",
        "description": "Add a line item to a draft bill. Price and GST are pulled from the catalog automatically unless unit_price is explicitly overridden. Blocked at the tool layer if it would oversell stock or sell below cost.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bill_id": {"type": "integer"},
                "product_name": {"type": "string"},
                "qty": {"type": "number"},
                "unit_price": {"type": "number", "description": "Only set if the owner explicitly states an override price."},
            },
            "required": ["bill_id", "product_name", "qty"],
        },
    },
    {
        "name": "remove_bill_item",
        "description": "Remove a product from a draft bill.",
        "input_schema": {"type": "object", "properties": {"bill_id": {"type": "integer"}, "product_name": {"type": "string"}}, "required": ["bill_id", "product_name"]},
    },
    {
        "name": "update_bill_item_qty",
        "description": "Change the quantity of a product already on a draft bill (e.g. 'make it 6 Maggi').",
        "input_schema": {
            "type": "object",
            "properties": {"bill_id": {"type": "integer"}, "product_name": {"type": "string"}, "new_qty": {"type": "number"}},
            "required": ["bill_id", "product_name", "new_qty"],
        },
    },
    {
        "name": "get_bill",
        "description": "Get the current state of a bill (items, tax breakup, totals) — use to show the owner what's on the bill so far.",
        "input_schema": {"type": "object", "properties": {"bill_id": {"type": "integer"}}, "required": ["bill_id"]},
    },
    {
        "name": "set_bill_payment",
        "description": "Set the payment mode for a draft bill before finalizing. Required before finalize_bill will succeed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bill_id": {"type": "integer"},
                "payment_mode": {"type": "string", "enum": ["cash", "upi", "card", "khata"]},
                "payment_ref": {"type": "string"},
                "customer_name": {"type": "string", "description": "Required if payment_mode is khata."},
            },
            "required": ["bill_id", "payment_mode"],
        },
    },
    {
        "name": "finalize_bill",
        "description": "Finalize a draft bill: atomically decrements stock and locks the bill. Idempotent — safe to call again with the same finalize_token if the request was retried (e.g. by Telegram); it will not double-bill.",
        "input_schema": {
            "type": "object",
            "properties": {"bill_id": {"type": "integer"}, "finalize_token": {"type": "string"}},
            "required": ["bill_id", "finalize_token"],
        },
    },
    {
        "name": "cancel_bill",
        "description": "Cancel a draft bill without affecting stock.",
        "input_schema": {"type": "object", "properties": {"bill_id": {"type": "integer"}}, "required": ["bill_id"]},
    },

    # ---------- Khata ----------
    {
        "name": "khata_credit",
        "description": "Put an amount on a customer's credit (khata). Creates the customer if they don't already have an account.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_name": {"type": "string"}, "amount": {"type": "number"}, "note": {"type": "string"}},
            "required": ["customer_name", "amount"],
        },
    },
    {
        "name": "khata_payment",
        "description": "Record a payment from a customer against their khata balance. Fails if the customer has no existing khata account.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_name": {"type": "string"}, "amount": {"type": "number"}},
            "required": ["customer_name", "amount"],
        },
    },
    {
        "name": "khata_balance",
        "description": "Get a customer's current khata balance.",
        "input_schema": {"type": "object", "properties": {"customer_name": {"type": "string"}}, "required": ["customer_name"]},
    },
    {
        "name": "khata_statement",
        "description": "Get recent khata transaction history for a customer.",
        "input_schema": {"type": "object", "properties": {"customer_name": {"type": "string"}}, "required": ["customer_name"]},
    },
    {
        "name": "list_khata_customers",
        "description": "List all customers with a khata account and their balances.",
        "input_schema": {"type": "object", "properties": {}},
    },

    # ---------- Analytics ----------
    {
        "name": "daily_close",
        "description": "Get the sales summary for a single day (defaults to today): revenue, tax collected, payment split, top items.",
        "input_schema": {"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD, optional"}}, "required": []},
    },
    {
        "name": "sales_summary",
        "description": "Get aggregated sales data over a date range, used before building the analysis deck.",
        "input_schema": {"type": "object", "properties": {"start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["start_date", "end_date"]},
    },
    {
        "name": "stock_health",
        "description": "Full stock health report across the catalog.",
        "input_schema": {"type": "object", "properties": {}},
    },

    # ---------- Preferences / memory ----------
    {
        "name": "set_preference",
        "description": "Persist a standing owner preference (e.g. default_payment_mode=upi, default_atta='Aashirvaad Atta 5kg'). This survives across chats — always use this instead of just remembering in conversation.",
        "input_schema": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}, "required": ["key", "value"]},
    },
    {
        "name": "get_all_preferences",
        "description": "Fetch all currently stored owner preferences.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_shop_info",
        "description": "Set shop name/GSTIN/address/phone shown on invoices.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "gstin": {"type": "string"}, "address": {"type": "string"}, "phone": {"type": "string"}},
            "required": [],
        },
    },

    # ---------- Documents ----------
    {
        "name": "generate_invoice_pdf",
        "description": "Generate a GST-correct PDF invoice for a finalized bill.",
        "input_schema": {"type": "object", "properties": {"bill_id": {"type": "integer"}}, "required": ["bill_id"]},
    },
    {
        "name": "generate_analysis_deck",
        "description": "Generate a PPTX business analysis deck (charts: revenue trend, top items, payment split, stock health) for a date range.",
        "input_schema": {"type": "object", "properties": {"start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["start_date", "end_date"]},
    },
]

_DISPATCH = {
    "search_products": inventory.search_products,
    "add_product": inventory.add_product,
    "receive_stock": inventory.receive_stock,
    "get_stock": inventory.get_stock,
    "list_low_stock": inventory.list_low_stock,
    "list_all_products": inventory.list_all_products,
    "start_bill": billing.start_bill,
    "add_bill_item": billing.add_bill_item,
    "remove_bill_item": billing.remove_bill_item,
    "update_bill_item_qty": billing.update_bill_item_qty,
    "get_bill": billing.get_bill,
    "set_bill_payment": billing.set_bill_payment,
    "finalize_bill": billing.finalize_bill,
    "cancel_bill": billing.cancel_bill,
    "khata_credit": khata.khata_credit,
    "khata_payment": khata.khata_payment,
    "khata_balance": khata.khata_balance,
    "khata_statement": khata.khata_statement,
    "list_khata_customers": khata.list_khata_customers,
    "daily_close": analytics.daily_close,
    "sales_summary": analytics.sales_summary,
    "stock_health": analytics.stock_health,
    "set_preference": preferences.set_preference,
    "get_all_preferences": preferences.get_all_preferences,
    "set_shop_info": preferences.set_shop_info,
    "generate_invoice_pdf": documents.generate_invoice_pdf,
    "generate_analysis_deck": documents.generate_analysis_deck,
}


def dispatch_tool(name: str, tool_input: dict):
    """Executes a tool call and returns a JSON-serializable dict.
    Business-rule violations (SkillError) are turned into a structured error
    result the model can read and react to — never a raw traceback."""
    fn = _DISPATCH.get(name)
    if not fn:
        return {"error": f"Unknown tool '{name}'."}
    try:
        result = fn(**tool_input)
        return result if result is not None else {"ok": True}
    except SkillError as e:
        return {"error": str(e)}
    except TypeError as e:
        return {"error": f"Bad arguments for {name}: {e}"}
