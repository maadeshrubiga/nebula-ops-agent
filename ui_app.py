from datetime import date
import os

from flask import Flask, render_template_string, request, send_file
from dotenv import load_dotenv

from db.database import get_conn, init_db, seed_demo_products
from skills import analytics, billing, documents, inventory, preferences
from skills.inventory import SkillError

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = "nebula-ui-demo"


init_db()
seed_demo_products()


HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Nebula Kirana Ops UI</title>
  <style>
    :root {
      --bg: #f4f0e8;
      --panel: #fffdf8;
      --text: #18242b;
      --muted: #6b7477;
      --primary: #df624b;
      --primary-dark: #ae3d31;
      --primary-soft: #fff0e9;
      --teal: #197875;
      --teal-soft: #e5f3f0;
      --success: #24714e;
      --success-soft: #e6f4eb;
      --error: #a9342b;
      --error-soft: #ffe5e0;
      --border: #e5ddd0;
      --shadow: 0 12px 30px rgba(47, 43, 35, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Trebuchet MS", Verdana, sans-serif;
      background-color: var(--bg);
      background-image: linear-gradient(135deg, rgba(255,255,255,.5) 25%, transparent 25%), linear-gradient(315deg, rgba(230,221,207,.28) 25%, transparent 25%);
      background-position: 0 0, 14px 14px;
      background-size: 28px 28px;
      color: var(--text);
    }
    .container { max-width: 1360px; margin: 0 auto; padding: 28px 30px 48px; }
    .topbar {
      display: flex; justify-content: space-between; align-items: center;
      background: #18242b; color: white; padding: 22px 26px; border-radius: 10px;
      box-shadow: var(--shadow);
      margin-bottom: 24px;
      border-bottom: 4px solid var(--primary);
    }
    .topbar-actions { display: flex; align-items: center; gap: 18px; }
    .telegram-link {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 9px 13px; border: 1px solid rgba(255,255,255,.25);
      border-radius: 6px; color: white; text-decoration: none;
      font-size: .85rem; font-weight: 700; background: rgba(255,255,255,.08);
      transition: background .15s ease, transform .15s ease;
    }
    .telegram-link:hover { background: rgba(255,255,255,.18); transform: translateY(-1px); }
    h1, h2, h3 { margin-top: 0; font-family: Georgia, serif; letter-spacing: 0; }
    h1 { font-size: clamp(1.55rem, 3vw, 2.3rem); margin-bottom: 2px; }
    h2 { font-size: 1.35rem; color: #25343a; margin-bottom: 18px; }
    .muted { color: var(--muted); }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 18px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 22px;
      box-shadow: var(--shadow);
    }
    form { display: grid; gap: 9px; }
    label { font-size: 0.82rem; font-weight: 700; color: #4f5b5d; letter-spacing: .02em; }
    input, select, button {
      font: inherit;
      font-size: 14px;
      border-radius: 6px;
    }
    input, select {
      width: 100%;
      padding: 11px 12px;
      border: 1px solid var(--border);
      background: #fffefa;
      color: var(--text);
      transition: border-color .15s ease, box-shadow .15s ease;
    }
    input:focus, select:focus {
      outline: none;
      border-color: var(--teal);
      box-shadow: 0 0 0 3px rgba(25, 120, 117, .12);
    }
    button {
      border: none;
      padding: 11px 16px;
      background: var(--primary);
      color: white;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 3px 0 var(--primary-dark);
      transition: transform .15s ease, background .15s ease;
    }
    button:hover { background: var(--primary-dark); transform: translateY(-1px); }
    button:active { transform: translateY(1px); box-shadow: none; }
    button:focus-visible { outline: 3px solid rgba(25, 120, 117, .35); outline-offset: 2px; }
    button.secondary {
      background: var(--teal-soft);
      color: #155f5d;
      border: 1px solid #b7dcd7;
      box-shadow: 0 3px 0 #a7cfca;
    }
    button.secondary:hover { background: #cfe9e5; }
    button.danger { background: #b8443a; }
    .alert {
      padding: 13px 16px;
      border-radius: 7px;
      margin-bottom: 20px;
      font-weight: 600;
      border-left: 5px solid currentColor;
    }
    .alert.success { background: var(--success-soft); color: var(--success); }
    .alert.error { background: var(--error-soft); color: var(--error); }
    .kpis {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 14px;
    }
    .kpi {
      background: var(--primary-soft);
      border-radius: 8px;
      padding: 16px;
      border: 1px solid #f2d4c8;
      border-top: 3px solid var(--primary);
    }
    .kpi:nth-child(2) { background: var(--teal-soft); border-color: #c6e3de; border-top-color: var(--teal); }
    .kpi:nth-child(3) { background: #fff7dc; border-color: #efdfae; border-top-color: #d19b2a; }
    .kpi:nth-child(4) { background: #edf0f3; border-color: #d9dfe2; border-top-color: #667985; }
    .kpi .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
    .kpi .value { font-size: 1.65rem; font-weight: bold; margin-top: 5px; color: #26363b; }
    .kpi .value:empty::after { content: "₹0"; }
    table {
      width: 100%; border-collapse: separate; border-spacing: 0;
      margin-top: 10px;
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 7px;
    }
    th, td { padding: 11px 12px; border-bottom: 1px solid var(--border); text-align: left; }
    th { background: #f1ece3; color: #536065; font-size: 11px; text-transform: uppercase; letter-spacing: .07em; }
    tr:last-child td { border-bottom: none; }
    tbody tr:nth-child(even) { background: #fcfaf5; }
    tbody tr:hover { background: #fff2eb; }
    .bill-summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin-top: 16px;
    }
    .summary-box {
      padding: 12px 14px;
      border-radius: 7px;
      background: #f8f3ea;
      border: 1px solid var(--border);
      color: #405055;
    }
    .bill-list { display: grid; gap: 8px; }
    .bill-row {
      display: grid; grid-template-columns: 1.3fr .9fr .9fr .8fr .8fr auto;
      gap: 12px; align-items: center; padding: 13px 14px;
      border: 1px solid var(--border); border-radius: 7px; background: #fffefa;
    }
    .bill-row:hover { background: #fff2eb; border-color: #efc8ba; }
    .bill-main { font-weight: 700; }
    .bill-meta { color: var(--muted); font-size: .82rem; }
    .bill-status, .bill-source {
      display: inline-block; width: fit-content; padding: 4px 8px;
      border-radius: 999px; font-size: .72rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: .05em;
    }
    .bill-status { background: var(--success-soft); color: var(--success); }
    .bill-status.draft { background: #fff4d6; color: #8b6519; }
    .bill-status.cancelled { background: var(--error-soft); color: var(--error); }
    .bill-source { background: var(--teal-soft); color: #155f5d; }
    .bill-link { color: var(--primary-dark); font-weight: 700; text-decoration: none; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
    .small { font-size: 13px; }
    a.link { color: var(--teal); text-decoration: none; font-weight: 700; }
    @media (max-width: 700px) {
      .container { padding: 16px 12px 32px; }
      .topbar { align-items: flex-start; flex-direction: column; gap: 8px; padding: 18px; }
      .panel { padding: 17px; }
      .bill-row { grid-template-columns: 1fr 1fr; gap: 8px; }
      .bill-row .bill-link { grid-column: 2; grid-row: 1 / span 2; align-self: center; justify-self: end; }
      th, td { padding: 9px 8px; font-size: 12px; }
      table { display: block; overflow-x: auto; white-space: nowrap; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="topbar">
      <div>
        <h1 style="margin:0;">Nebula Kirana Ops UI</h1>
      </div>
      <div class="topbar-actions">
        <a class="telegram-link" href="{{ telegram_url }}" target="_blank" rel="noopener">✈ {{ telegram_label }}</a>
        <div class="muted" style="color:#dbe7ff;">Shop: {{ shop_info.name }}</div>
      </div>
    </div>

    {% if message %}
      <div class="alert {{ status }}">{{ message }}</div>
    {% endif %}

    <div class="panel">
      <h2>Daily close summary</h2>
      <div class="kpis">
        <div class="kpi"><div class="label">Date</div><div class="value">{{ summary.date }}</div></div>
        <div class="kpi"><div class="label">Bills</div><div class="value">{{ summary.total_bills }}</div></div>
        <div class="kpi"><div class="label">Revenue</div><div class="value">₹{{ summary.total_revenue }}</div></div>
        <div class="kpi"><div class="label">Tax</div><div class="value">₹{{ summary.total_tax_collected }}</div></div>
      </div>
      {% if summary.message %}
        <p class="muted">{{ summary.message }}</p>
      {% endif %}
    </div>

    <div class="panel">
      <h2>Recent bills</h2>
      {% if recent_bills %}
        <div class="bill-list">
          {% for recent_bill in recent_bills %}
            <div class="bill-row">
              <div>
                <div class="bill-main">Bill #{{ recent_bill.id }} · {{ recent_bill.customer_name or 'Walk-in' }}</div>
                <div class="bill-meta">{{ recent_bill.created_at }}</div>
              </div>
              <span class="bill-source">{{ recent_bill.source }}</span>
              <span class="bill-status {{ recent_bill.status }}">{{ recent_bill.status }}</span>
              <div class="bill-meta">{{ recent_bill.payment_mode or 'Payment pending' }}</div>
              <strong>₹{{ recent_bill.grand_total }}</strong>
              <a class="bill-link" href="/bill/{{ recent_bill.id }}">View bill</a>
            </div>
          {% endfor %}
        </div>
      {% else %}
        <p class="muted">No bills yet. Bills created in Telegram will appear here automatically.</p>
      {% endif %}
    </div>

    <div class="grid">
      <div class="panel">
        <h2>Add product</h2>
        <form action="/add-product" method="post">
          <label>Name</label>
          <input name="name" required>
          <label>Unit</label>
          <input name="unit" value="packet" required>
          <label>GST rate</label>
          <input name="gst_rate" type="number" step="0.01" value="5" required>
          <label>Cost price</label>
          <input name="cost_price" type="number" step="0.01" value="0" required>
          <label>Sell price</label>
          <input name="sell_price" type="number" step="0.01" value="0" required>
          <label>Quantity</label>
          <input name="quantity" type="number" step="0.01" value="0">
          <label>Reorder level</label>
          <input name="reorder_level" type="number" step="0.01" value="0">
          <label>Loose item?</label>
          <select name="is_loose">
            <option value="0">No</option>
            <option value="1">Yes</option>
          </select>
          <button type="submit">Add Product</button>
        </form>
      </div>

      <div class="panel">
        <h2>Receive stock</h2>
        <form action="/receive-stock" method="post">
          <label>Product</label>
          <select name="product_name" required>
            {% for product in products %}
              <option value="{{ product.name }}">{{ product.name }}</option>
            {% endfor %}
          </select>
          <label>Quantity</label>
          <input name="quantity" type="number" step="0.01" value="10" required>
          <label>Cost price (optional)</label>
          <input name="cost_price" type="number" step="0.01">
          <label>Sell price (optional)</label>
          <input name="sell_price" type="number" step="0.01">
          <button type="submit">Receive Stock</button>
        </form>
      </div>

      <div class="panel">
        <h2>Create bill</h2>
        <form action="/create-bill" method="post">
          <label>Customer name</label>
          <input name="customer_name" placeholder="Walk-in / Ramesh">
          <label>Payment mode</label>
          <select name="payment_mode">
            <option value="">Not set yet</option>
            <option value="cash">Cash</option>
            <option value="upi">UPI</option>
            <option value="card">Card</option>
            <option value="khata">Khata</option>
          </select>
          <button type="submit">Create Bill</button>
        </form>
      </div>
    </div>

    <div class="grid">
      <div class="panel">
        <h2>Low stock</h2>
        {% if low_stock %}
          <table>
            <thead>
              <tr><th>Product</th><th>Quantity</th><th>Reorder</th></tr>
            </thead>
            <tbody>
              {% for item in low_stock %}
                <tr>
                  <td>{{ item.name }}</td>
                  <td>{{ item.quantity }}</td>
                  <td>{{ item.reorder_level }}</td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        {% else %}
          <p class="muted">No low-stock items.</p>
        {% endif %}
      </div>

      <div class="panel">
        <h2>Generate analysis deck</h2>
        <form action="/generate-deck" method="post">
          <label>Start date</label>
          <input type="date" name="start_date" value="{{ today }}" required>
          <label>End date</label>
          <input type="date" name="end_date" value="{{ today }}" required>
          <button type="submit">Generate PPTX</button>
        </form>
      </div>
    </div>

    <div class="panel">
      <h2>Products</h2>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Unit</th>
            <th>Qty</th>
            <th>Cost</th>
            <th>Sell</th>
            <th>GST</th>
          </tr>
        </thead>
        <tbody>
          {% for product in products %}
            <tr>
              <td>{{ product.name }}</td>
              <td>{{ product.unit }}</td>
              <td>{{ product.quantity }}</td>
              <td>{{ product.cost_price }}</td>
              <td>{{ product.sell_price }}</td>
              <td>{{ product.gst_rate }}%</td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    {% if bill %}
      <div class="panel">
        <h2>Bill #{{ bill.bill_id }}</h2>
        <div class="bill-summary">
          <div class="summary-box"><strong>Customer</strong><br>{{ bill.customer_name or 'Walk-in' }}</div>
          <div class="summary-box"><strong>Payment</strong><br>{{ bill.payment_mode or 'Not set' }}</div>
          <div class="summary-box"><strong>Subtotal</strong><br>₹{{ bill.subtotal }}</div>
          <div class="summary-box"><strong>CGST</strong><br>₹{{ bill.cgst_total }}</div>
          <div class="summary-box"><strong>SGST</strong><br>₹{{ bill.sgst_total }}</div>
          <div class="summary-box"><strong>Grand total</strong><br>₹{{ bill.grand_total }}</div>
        </div>

        <div class="actions">
          <form action="/bill/{{ bill.bill_id }}/add-item" method="post" style="display:flex; gap:10px; flex-wrap:wrap; width:100%;">
            <select name="product_name" required style="max-width:360px;">
              {% for product in products %}
                <option value="{{ product.name }}">{{ product.name }}</option>
              {% endfor %}
            </select>
            <input type="number" name="qty" value="1" min="1" step="0.01" style="max-width:120px;">
            <button type="submit">Add item</button>
          </form>
        </div>

        <div class="actions">
          <form action="/bill/{{ bill.bill_id }}/payment" method="post" style="display:flex; gap:10px; flex-wrap:wrap; width:100%;">
            <select name="payment_mode">
              <option value="cash">Cash</option>
              <option value="upi">UPI</option>
              <option value="card">Card</option>
              <option value="khata">Khata</option>
            </select>
            <input type="text" name="customer_name" placeholder="Customer name for khata" value="{{ bill.customer_name or '' }}">
            <button class="secondary" type="submit">Set payment</button>
          </form>
        </div>

        <div class="actions">
          <form action="/bill/{{ bill.bill_id }}/finalize" method="post">
            <button type="submit">Finalize bill</button>
          </form>
          <form action="/bill/{{ bill.bill_id }}/invoice" method="post">
            <button class="secondary" type="submit">Generate Invoice PDF</button>
          </form>
        </div>

        {% if bill["items"] %}
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Qty</th>
                <th>Unit Price</th>
                <th>Taxable</th>
                <th>CGST</th>
                <th>SGST</th>
                <th>Line Total</th>
              </tr>
            </thead>
            <tbody>
              {% for item in bill["items"] %}
                <tr>
                  <td>{{ item.product_name }}</td>
                  <td>{{ item.qty }}</td>
                  <td>₹{{ item.unit_price }}</td>
                  <td>₹{{ item.taxable_value }}</td>
                  <td>₹{{ item.cgst_amount }}</td>
                  <td>₹{{ item.sgst_amount }}</td>
                  <td>₹{{ item.line_total }}</td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        {% else %}
          <p class="muted">No items yet. Add items to build the bill.</p>
        {% endif %}
      </div>
    {% endif %}
  </div>
</body>
</html>
"""


def _get_products():
    return inventory.list_all_products()


def _get_recent_bills(limit=12):
    conn = get_conn()
    rows = conn.execute(
        """SELECT id, status, customer_name, payment_mode, grand_total, created_at,
                  CASE WHEN chat_id IS NULL THEN 'Browser' ELSE 'Telegram' END AS source
           FROM bills ORDER BY id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _get_context(message=None, status="success", bill=None):
    products = _get_products()
    low_stock = inventory.list_low_stock()
    summary = analytics.daily_close()
    shop_info = preferences.get_shop_info()
    recent_bills = _get_recent_bills()
    bot_username = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
    telegram_url = f"https://t.me/{bot_username}" if bot_username else "https://web.telegram.org/"
    telegram_label = "Open Bot" if bot_username else "Open Telegram"
    return render_template_string(
        HTML_TEMPLATE,
        products=products,
        low_stock=low_stock,
        summary=summary,
        shop_info=shop_info,
        recent_bills=recent_bills,
        telegram_url=telegram_url,
        telegram_label=telegram_label,
        message=message,
        status=status,
        bill=bill,
        today=date.today().isoformat(),
    )


@app.route("/")
def index():
    return _get_context()


@app.route("/add-product", methods=["POST"])
def add_product_route():
    try:
        inventory.add_product(
            name=request.form.get("name", "").strip(),
            unit=request.form.get("unit", "packet").strip(),
            gst_rate=float(request.form.get("gst_rate", 0)),
            cost_price=float(request.form.get("cost_price", 0)),
            sell_price=float(request.form.get("sell_price", 0)),
            is_loose=bool(int(request.form.get("is_loose", 0))),
            quantity=float(request.form.get("quantity", 0)),
            reorder_level=float(request.form.get("reorder_level", 0)),
        )
        return _get_context(message="Product added successfully.", status="success")
    except (SkillError, ValueError) as exc:
        return _get_context(message=str(exc), status="error")


@app.route("/receive-stock", methods=["POST"])
def receive_stock_route():
    try:
        inventory.receive_stock(
            product_name=request.form.get("product_name", "").strip(),
            quantity=float(request.form.get("quantity", 0)),
            cost_price=request.form.get("cost_price") or None,
            sell_price=request.form.get("sell_price") or None,
        )
        return _get_context(message="Stock received successfully.", status="success")
    except (SkillError, ValueError) as exc:
        return _get_context(message=str(exc), status="error")


@app.route("/create-bill", methods=["POST"])
def create_bill_route():
    try:
        customer_name = request.form.get("customer_name", "").strip() or None
        payment_mode = request.form.get("payment_mode", "").strip() or None
        bill = billing.start_bill(customer_name=customer_name)
        if payment_mode:
            billing.set_bill_payment(bill["bill_id"], payment_mode, customer_name=customer_name)
        return _get_context(message="Bill created successfully.", bill=billing.get_bill(bill["bill_id"]), status="success")
    except Exception as exc:
        return _get_context(message=str(exc), status="error")


@app.route("/bill/<int:bill_id>")
def bill_page(bill_id):
    try:
        bill = billing.get_bill(bill_id)
        return _get_context(bill=bill)
    except Exception as exc:
        return _get_context(message=str(exc), status="error")


@app.route("/bill/<int:bill_id>/add-item", methods=["POST"])
def bill_add_item_route(bill_id):
    try:
        billing.add_bill_item(
            bill_id=bill_id,
            product_name=request.form.get("product_name", "").strip(),
            qty=float(request.form.get("qty", 0)),
        )
        return _get_context(message="Item added to bill.", bill=billing.get_bill(bill_id), status="success")
    except Exception as exc:
        return _get_context(message=str(exc), status="error", bill=billing.get_bill(bill_id))


@app.route("/bill/<int:bill_id>/payment", methods=["POST"])
def bill_payment_route(bill_id):
    try:
        customer_name = request.form.get("customer_name", "").strip() or None
        payment_mode = request.form.get("payment_mode", "").strip()
        billing.set_bill_payment(bill_id, payment_mode, customer_name=customer_name)
        return _get_context(message="Payment mode updated.", bill=billing.get_bill(bill_id), status="success")
    except Exception as exc:
        return _get_context(message=str(exc), status="error", bill=billing.get_bill(bill_id))


@app.route("/bill/<int:bill_id>/finalize", methods=["POST"])
def bill_finalize_route(bill_id):
    try:
        result = billing.finalize_bill(bill_id, finalize_token=f"ui-{bill_id}")
        return _get_context(message=f"Bill finalized successfully. Grand total: ₹{result['grand_total']}", bill=result, status="success")
    except Exception as exc:
        return _get_context(message=str(exc), status="error", bill=billing.get_bill(bill_id))


@app.route("/bill/<int:bill_id>/invoice", methods=["POST"])
def bill_invoice_route(bill_id):
    try:
        invoice = documents.generate_invoice_pdf(bill_id)
        return send_file(invoice["file_path"], as_attachment=True, download_name=f"invoice_{bill_id}.pdf")
    except Exception as exc:
        return _get_context(message=str(exc), status="error", bill=billing.get_bill(bill_id))


@app.route("/generate-deck", methods=["POST"])
def generate_deck_route():
    try:
        start_date = request.form.get("start_date", date.today().isoformat())
        end_date = request.form.get("end_date", date.today().isoformat())
        deck = documents.generate_analysis_deck(start_date, end_date)
        return send_file(deck["file_path"], as_attachment=True, download_name=f"analysis_{start_date}_to_{end_date}.pptx")
    except Exception as exc:
        return _get_context(message=str(exc), status="error")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
