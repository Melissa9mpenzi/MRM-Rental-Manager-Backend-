"""Enterprise PDF receipts with QR verification codes."""
from __future__ import annotations

import io
import os
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import settings


def _status_color(status: str) -> colors.Color:
    key = (status or "paid").lower()
    palette = {
        "paid": colors.HexColor("#22c55e"),
        "pending": colors.HexColor("#f59e0b"),
        "failed": colors.HexColor("#ef4444"),
        "escrowed": colors.HexColor("#8b5cf6"),
        "refunded": colors.HexColor("#64748b"),
    }
    return palette.get(key, colors.HexColor("#22c55e"))


def _qr_image(verify_url: str):
    import qrcode

    qr = qrcode.QRCode(version=1, box_size=4, border=2)
    qr.add_data(verify_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0a1210", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Image(buf, width=3.2 * cm, height=3.2 * cm)


def build_receipt_pdf_bytes(
    receipt: dict[str, Any],
    *,
    verify_url: str,
) -> bytes:
    """Generate enterprise PDF in memory (works on Vercel serverless)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    _build_receipt_pdf_story(doc, receipt, verify_url=verify_url)
    return buffer.getvalue()


def build_receipt_pdf(
    receipt: dict[str, Any],
    *,
    verify_url: str,
    upload_dir: str,
) -> str:
    """Generate enterprise PDF on disk and return web path /uploads/receipts/..."""
    receipts_dir = os.path.join(upload_dir, "receipts", "enterprise")
    os.makedirs(receipts_dir, exist_ok=True)
    safe_num = receipt["receipt_number"].replace("/", "-")
    filename = f"{safe_num}.pdf"
    filepath = os.path.join(receipts_dir, filename)

    content = build_receipt_pdf_bytes(receipt, verify_url=verify_url)
    with open(filepath, "wb") as f:
        f.write(content)
    return f"/uploads/receipts/enterprise/{filename}"


def _build_receipt_pdf_story(
    doc: SimpleDocTemplate,
    receipt: dict[str, Any],
    *,
    verify_url: str,
) -> None:
    styles = getSampleStyleSheet()
    navy = colors.HexColor("#0c1219")
    teal = colors.HexColor("#00a376")
    muted = colors.HexColor("#64748b")

    title = ParagraphStyle("title", parent=styles["Heading1"], textColor=navy, fontSize=18, spaceAfter=2)
    badge = ParagraphStyle("badge", parent=styles["Normal"], fontSize=9, textColor=colors.white, alignment=1)
    label = ParagraphStyle("label", parent=styles["Normal"], fontSize=8, textColor=muted)
    value = ParagraphStyle("value", parent=styles["Normal"], fontSize=9, textColor=navy, fontName="Helvetica-Bold")
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, textColor=navy)

    status = str(receipt.get("status") or "paid").upper()
    rtype = str(receipt.get("receipt_type") or "rent_payment").replace("_", " ").title()

    story = [
        Paragraph("RentDirect <font color='#00a376'>UG</font>", title),
        Paragraph("Blockchain Payment Receipt", ParagraphStyle("sub", parent=body, fontSize=11, textColor=muted)),
        Spacer(1, 0.3 * cm),
    ]

    header_data = [
        [
            Paragraph(f"<b>Receipt #</b><br/>{receipt.get('receipt_number', '—')}", body),
            Paragraph(f"<b>Date</b><br/>{receipt.get('issued_at_label', '—')}", body),
            Paragraph(
                f'<para backColor="{_status_color(status).hexval()}" align="center">'
                f"<font color='white'><b>{status}</b></font></para>",
                badge,
            ),
        ]
    ]
    ht = Table(header_data, colWidths=[6 * cm, 5 * cm, 4 * cm])
    ht.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.extend([ht, Spacer(1, 0.5 * cm)])

    story.append(Paragraph("Property", ParagraphStyle("sec", parent=value, fontSize=10, textColor=teal)))
    prop_rows = [
        ["Property", receipt.get("property_name") or "—"],
        ["Address", receipt.get("property_address") or "—"],
        ["Unit", receipt.get("unit_number") or "—"],
        ["Landlord", receipt.get("landlord_name") or "—"],
        ["Lease", f"{receipt.get('lease_start') or '—'} → {receipt.get('lease_end') or '—'}"],
    ]
    story.extend([_kv_table(prop_rows), Spacer(1, 0.4 * cm)])

    story.append(Paragraph("Payment", ParagraphStyle("sec2", parent=value, fontSize=10, textColor=teal)))
    pay_rows = [
        ["Tenant", receipt.get("tenant_name") or "—"],
        ["Period", receipt.get("period_label") or "—"],
        ["Method", (receipt.get("payment_method") or "—").replace("_", " ").title()],
        ["Reference", receipt.get("transaction_reference") or "—"],
        ["Currency", receipt.get("currency") or "UGX"],
    ]
    story.extend([_kv_table(pay_rows), Spacer(1, 0.3 * cm)])

    amt = receipt.get("amount_display") or f"{receipt.get('currency', 'UGX')} {float(receipt.get('amount', 0)):,.0f}"
    amt_table = Table([["AMOUNT PAID", amt]], colWidths=[5 * cm, 10 * cm])
    amt_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), teal),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (0, 0), 9),
                ("FONTSIZE", (1, 0), (1, 0), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    story.extend([amt_table, Spacer(1, 0.4 * cm)])

    if receipt.get("tx_hash") or receipt.get("wallet_address"):
        story.append(Paragraph("Blockchain proof", ParagraphStyle("sec3", parent=value, fontSize=10, textColor=teal)))
        chain_rows = [
            ["Network", receipt.get("network") or settings.sui_network or "Sui"],
            ["Wallet", receipt.get("wallet_address") or "—"],
            ["TX Hash", receipt.get("tx_hash") or "—"],
            ["Contract", receipt.get("contract_id") or "—"],
            ["Walrus proof", receipt.get("walrus_blob_id") or "—"],
        ]
        story.extend([_kv_table(chain_rows), Spacer(1, 0.3 * cm)])

    if receipt.get("tax_id") or receipt.get("vat_amount"):
        story.append(Paragraph("Government tax (URA)", ParagraphStyle("sec4", parent=value, fontSize=10, textColor=teal)))
        tax_rows = [
            ["Tax ID", receipt.get("tax_id") or "—"],
            ["URA code", receipt.get("ura_compliance_code") or "—"],
            ["VAT", receipt.get("vat_display") or "—"],
            ["Tax rate", f"{receipt.get('tax_percentage') or 0}%"],
        ]
        story.extend([_kv_table(tax_rows), Spacer(1, 0.3 * cm)])

    if receipt.get("smart_summary"):
        story.extend(
            [
                Paragraph("Summary", ParagraphStyle("sum", parent=label, fontSize=8, textColor=muted)),
                Paragraph(receipt["smart_summary"], body),
                Spacer(1, 0.3 * cm),
            ]
        )

    qr_row = Table(
        [
            [
                _qr_image(verify_url),
                Paragraph(
                    f"<b>Scan to Verify Receipt</b><br/>Tamper-proof trust link:<br/>"
                    f"<font size='7'>{verify_url}</font><br/><br/>"
                    f"Checksum: <font size='7'>{receipt.get('checksum', '')[:16]}…</font><br/>"
                    f"Signature: <font size='7'>{receipt.get('digital_signature', '')[:20]}…</font>",
                    body,
                ),
            ]
        ],
        colWidths=[4 * cm, 11 * cm],
    )
    qr_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.extend([qr_row, Spacer(1, 0.5 * cm)])

    support = settings.email_support_email or "support@rentdirect.ug"
    story.append(
        Paragraph(
            f"<font size='7' color='#64748b'>"
            f"RentDirect UG — National rental payment infrastructure · Uganda<br/>"
            f"Support: {support} · Terms apply · Digitally signed system receipt<br/>"
            f"Government compliance seal · Verify at verify.rentdirect.ug"
            f"</font>",
            body,
        )
    )

    doc.build(story)


def _kv_table(rows: list[list[str]]) -> Table:
    dark = colors.HexColor("#0c1219")
    muted = colors.HexColor("#64748b")
    t = Table(rows, colWidths=[4 * cm, 11 * cm])
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), muted),
                ("TEXTCOLOR", (1, 0), (1, -1), dark),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t
