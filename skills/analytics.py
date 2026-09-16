"""Analytics skill — aggregates over finalized bills for daily close and the analysis deck."""
from datetime import datetime, timedelta
from db.database import get_conn
from skills.inventory import SkillError


def _date_bounds(date_str: str = None):
    if date_str:
        day = datetime.strptime(date_str, "%Y-%m-%d")
    else:
        day = datetime.now()
    start = day.strftime("%Y-%m-%d 00:00:00")
    end = (day + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    return start, end


def daily_close(date: str = None):
    """date: 'YYYY-MM-DD', defaults to today."""
    start, end = _date_bounds(date)
    conn = get_conn()
    bills = conn.execute(
        "SELECT * FROM bills WHERE status='finalized' AND finalized_at >= ? AND finalized_at < ?",
        (start, end),
    ).fetchall()
    if not bills:
        return {
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "total_bills": 0,
            "total_revenue": 0,
            "total_tax_collected": 0,
            "message": "No sales recorded for this day.",
        }

    total_revenue = sum(b["grand_total"] for b in bills)
    total_tax = sum(b["cgst_total"] + b["sgst_total"] for b in bills)
    by_mode = {}
    for b in bills:
        by_mode[b["payment_mode"]] = by_mode.get(b["payment_mode"], 0) + b["grand_total"]

    bill_ids = [b["id"] for b in bills]
    placeholders = ",".join("?" * len(bill_ids))
    top_items = conn.execute(
        f"""SELECT product_name, SUM(qty) as total_qty, SUM(line_total) as revenue
            FROM bill_items WHERE bill_id IN ({placeholders})
            GROUP BY product_name ORDER BY revenue DESC LIMIT 5""",
        bill_ids,
    ).fetchall()

    return {
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "total_bills": len(bills),
        "total_revenue": round(total_revenue, 2),
        "total_tax_collected": round(total_tax, 2),
        "payment_mode_breakdown": {k: round(v, 2) for k, v in by_mode.items()},
        "top_items": [dict(r) for r in top_items],
    }


def sales_summary(start_date: str, end_date: str):
    """Inclusive date range 'YYYY-MM-DD'. Used to build the analysis deck."""
    start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y-%m-%d 00:00:00")
    end = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    conn = get_conn()
    bills = conn.execute(
        "SELECT * FROM bills WHERE status='finalized' AND finalized_at >= ? AND finalized_at < ?",
        (start, end),
    ).fetchall()

    daily_totals = {}
    for b in bills:
        day = b["finalized_at"][:10]
        daily_totals[day] = daily_totals.get(day, 0) + b["grand_total"]

    bill_ids = [b["id"] for b in bills] or [-1]
    placeholders = ",".join("?" * len(bill_ids))
    top_items = conn.execute(
        f"""SELECT product_name, SUM(qty) as total_qty, SUM(line_total) as revenue
            FROM bill_items WHERE bill_id IN ({placeholders})
            GROUP BY product_name ORDER BY revenue DESC LIMIT 8""",
        bill_ids,
    ).fetchall()

    by_mode = {}
    for b in bills:
        by_mode[b["payment_mode"]] = by_mode.get(b["payment_mode"], 0) + b["grand_total"]

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_bills": len(bills),
        "total_revenue": round(sum(b["grand_total"] for b in bills), 2),
        "total_tax_collected": round(sum(b["cgst_total"] + b["sgst_total"] for b in bills), 2),
        "daily_totals": daily_totals,
        "top_items": [dict(r) for r in top_items],
        "payment_mode_breakdown": {k: round(v, 2) for k, v in by_mode.items()},
    }


def stock_health():
    conn = get_conn()
    rows = conn.execute(
        "SELECT name, quantity, unit, reorder_level FROM products WHERE is_active=1 ORDER BY (quantity - reorder_level) ASC"
    ).fetchall()
    low = [dict(r) for r in rows if r["quantity"] <= r["reorder_level"]]
    return {"low_stock": low, "all_products": [dict(r) for r in rows]}
