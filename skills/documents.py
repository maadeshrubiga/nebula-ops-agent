"""
Document generation skill: real artifacts, not screenshots.

generate_invoice_pdf  -> GST-correct PDF invoice for a finalized bill (reportlab)
generate_analysis_deck -> PPTX with real matplotlib charts (python-pptx)

Both write into OUTPUT_DIR and return an absolute file_path. The bot layer
watches tool results for a "file_path" key and uploads that file to Telegram
as a document.
"""
import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE

from skills import billing, analytics, preferences
from skills.inventory import SkillError

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def generate_invoice_pdf(bill_id: int):
    bill = billing.get_bill(bill_id)
    if bill["status"] != "finalized":
        raise SkillError(f"Bill {bill_id} is not finalized yet — finalize it before invoicing.")

    shop = preferences.get_shop_info()
    path = os.path.join(OUTPUT_DIR, f"invoice_{bill_id}.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title2", parent=styles["Title"], fontSize=16)
    small = styles["Normal"]

    elements = [
        Paragraph(shop.get("name", "Kirana Store"), title_style),
        Paragraph(f"GSTIN: {shop.get('gstin', '-')}  |  {shop.get('address', '')}  |  Ph: {shop.get('phone', '')}", small),
        Spacer(1, 8),
        Paragraph(f"<b>Tax Invoice</b>  —  Bill #{bill_id}", styles["Heading2"]),
        Paragraph(f"Date: {datetime.now().strftime('%d-%b-%Y %H:%M')}", small),
        Paragraph(f"Customer: {bill.get('customer_name') or 'Walk-in'}", small),
        Paragraph(f"Payment Mode: {bill.get('payment_mode', '-').upper()}", small),
        Spacer(1, 10),
    ]

    table_data = [["Item", "Qty", "Unit Price", "Taxable Val", "CGST", "SGST", "Line Total"]]
    for item in bill["items"]:
        table_data.append([
            item["product_name"],
            f"{item['qty']} {item['unit'] or ''}",
            f"₹{item['unit_price']:.2f}",
            f"₹{item['taxable_value']:.2f}",
            f"₹{item['cgst_amount']:.2f} ({item['gst_rate']/2:.1f}%)",
            f"₹{item['sgst_amount']:.2f} ({item['gst_rate']/2:.1f}%)",
            f"₹{item['line_total']:.2f}",
        ])
    table_data.append(["", "", "", "Subtotal", "", "", f"₹{bill['subtotal']:.2f}"])
    table_data.append(["", "", "", "CGST Total", f"₹{bill['cgst_total']:.2f}", "", ""])
    table_data.append(["", "", "", "SGST Total", "", f"₹{bill['sgst_total']:.2f}", ""])
    table_data.append(["", "", "", "GRAND TOTAL", "", "", f"₹{bill['grand_total']:.2f}"])

    t = Table(table_data, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4a1942")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -5), 0.4, colors.grey),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -4), (-1, -4), 0.8, colors.black),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 14))
    elements.append(Paragraph("Thank you for shopping with us!", small))

    doc.build(elements)
    return {"file_path": os.path.abspath(path), "bill_id": bill_id, "message": f"Invoice generated for bill #{bill_id}."}


def _add_chart_slide(prs, title, chart_type, categories, series_name, values):
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = title
    chart_data = CategoryChartData()
    chart_data.categories = categories
    chart_data.add_series(series_name, values)
    x, y, cx, cy = Inches(0.7), Inches(1.4), Inches(8.6), Inches(5.2)
    slide.shapes.add_chart(chart_type, x, y, cx, cy, chart_data)
    return slide


def generate_analysis_deck(start_date: str, end_date: str):
    data = analytics.sales_summary(start_date, end_date)
    shop = preferences.get_shop_info()

    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(6.5)

    # Title slide
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = f"{shop.get('name', 'Kirana Store')} — Sales Analysis"
    slide.placeholders[1].text = f"{start_date} to {end_date}"

    # Summary slide
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Summary"
    body = slide.placeholders[1].text_frame
    body.text = f"Total Bills: {data['total_bills']}"
    p = body.add_paragraph(); p.text = f"Total Revenue: ₹{data['total_revenue']:.2f}"
    p = body.add_paragraph(); p.text = f"Total GST Collected: ₹{data['total_tax_collected']:.2f}"
    for mode, amt in data["payment_mode_breakdown"].items():
        p = body.add_paragraph(); p.text = f"  {mode.upper()}: ₹{amt:.2f}"

    # Daily revenue trend
    if data["daily_totals"]:
        days = sorted(data["daily_totals"].keys())
        _add_chart_slide(prs, "Daily Revenue Trend", XL_CHART_TYPE.LINE_MARKERS,
                          days, "Revenue (₹)", [data["daily_totals"][d] for d in days])

    # Top items by revenue
    if data["top_items"]:
        names = [i["product_name"] for i in data["top_items"]]
        revs = [i["revenue"] for i in data["top_items"]]
        _add_chart_slide(prs, "Top Items by Revenue", XL_CHART_TYPE.BAR_CLUSTERED, names, "Revenue (₹)", revs)

    # Payment mode split
    if data["payment_mode_breakdown"]:
        modes = list(data["payment_mode_breakdown"].keys())
        amts = list(data["payment_mode_breakdown"].values())
        _add_chart_slide(prs, "Payment Mode Split", XL_CHART_TYPE.PIE, modes, "Amount (₹)", amts)

    # Stock health
    health = analytics.stock_health()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Stock Health — Reorder Needed"
    body = slide.placeholders[1].text_frame
    if health["low_stock"]:
        body.text = f"{health['low_stock'][0]['name']}: {health['low_stock'][0]['quantity']} {health['low_stock'][0]['unit']} left"
        for item in health["low_stock"][1:]:
            p = body.add_paragraph(); p.text = f"{item['name']}: {item['quantity']} {item['unit']} left"
    else:
        body.text = "All stock levels healthy."

    path = os.path.join(OUTPUT_DIR, f"analysis_{start_date}_to_{end_date}.pptx")
    prs.save(path)
    return {"file_path": os.path.abspath(path), "message": f"Analysis deck generated for {start_date} to {end_date}."}
