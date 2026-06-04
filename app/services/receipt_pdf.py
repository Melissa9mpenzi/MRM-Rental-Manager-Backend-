"""Professional PDF receipts with QR verification (no sensitive internals on document)."""
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
from app.services.receipt_redaction import receipt_pdf_fields


def _status_color(status: str) -> colors.Color:
    key = (status or "paid").lower()
    palette = {
        "paid": colors.HexColor("#15803d"),
        "pending": colors.HexColor("#b45309"),
        "failed": colors.HexColor("#b91c1c"),
        "escrowed": colors.HexColor("#6d28d9"),
        "refunded": colors.HexColor("#475569"),
    }
    return palette.get(key, colors.HexColor("#15803d"))


def _qr_image(verify_url: str):
    import qrcode

    qr = qrcode.QRCode(version=1, box_size=4, border=2)
    qr.add_data(verify_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0c1219", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Image(buf, width=2.8 * cm, height=2.8 * cm)


def build_receipt_pdf_bytes(
    receipt: dict[str, Any],
    *,
    verify_url: str,
) -> bytes:
    """Generate enterprise PDF in memory (works on Vercel serverless)."""
    safe = receipt_pdf_fields(receipt)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1.8 * cm, bottomMargin=1.8 * cm)
    _build_receipt_pdf_story(doc, safe, verify_url=verify_url)
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
    navy = colors.HexColor("#0f172a")
    teal = colors.HexColor("#0d9488")
    muted = colors.HexColor("#64748b")
    line = colors.HexColor("#e2e8f0")

    title = ParagraphStyle(
        "title",
        parent=styles["Heading1"],
        textColor=navy,
        fontSize=16,
        fontName="Helvetica-Bold",
        spaceAfter=2,
    )
    subtitle = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=9, textColor=muted, spaceAfter=0)
    section = ParagraphStyle("section", parent=styles["Normal"], fontSize=9, textColor=teal, fontName="Helvetica-Bold")
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, textColor=navy)
    fine = ParagraphStyle("fine", parent=styles["Normal"], fontSize=7, textColor=muted, leading=10)

    status = str(receipt.get("status") or "paid").upper()
    status_color = _status_color(status)

    story = [
        Paragraph("RentDirect <font color='#0d9488'>UG</font>", title),
        Paragraph("Official Payment Receipt", subtitle),
        Spacer(1, 0.35 * cm),
    ]

    meta = Table(
        [
            [
                Paragraph(f"<b>Receipt No.</b><br/>{receipt.get('receipt_number', '—')}", body),
                Paragraph(f"<b>Date issued</b><br/>{receipt.get('issued_at_label', '—')}", body),
                Paragraph(
                    f'<para backColor="{status_color.hexval()}" align="center" '
                    f'leftIndent="4" rightIndent="4" spaceBefore="2" spaceAfter="2">'
                    f"<font color='white' size='8'><b>{status}</b></font></para>",
                    ParagraphStyle("badge", parent=body, alignment=1),
                ),
            ]
        ],
        colWidths=[5.5 * cm, 5.5 * cm, 4 * cm],
    )
    meta.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, line),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([meta, Spacer(1, 0.45 * cm)])

    amt = receipt.get("amount_display") or (
        f"{receipt.get('currency', 'UGX')} {float(receipt.get('amount', 0)):,.0f}"
    )
    amt_table = Table([["Amount received", amt]], colWidths=[5 * cm, 10 * cm])
    amt_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), teal),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (0, 0), 8),
                ("FONTSIZE", (1, 0), (1, 0), 13),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ]
        )
    )
    story.extend([amt_table, Spacer(1, 0.45 * cm)])

    story.append(Paragraph("Tenancy", section))
    tenancy_rows = [
        ["Property", receipt.get("property_name") or "—"],
        ["Location", receipt.get("property_address") or "—"],
        ["Unit", receipt.get("unit_number") or "—"],
        ["Billing period", receipt.get("period_label") or "—"],
        ["Paid by", receipt.get("tenant_name") or "—"],
    ]
    story.extend([_kv_table(tenancy_rows), Spacer(1, 0.35 * cm)])

    story.append(Paragraph("Payment", section))
    pay_rows = [
        ["Method", (receipt.get("payment_method") or "—").replace("_", " ").title()],
        ["Reference", receipt.get("transaction_reference") or "—"],
        ["Currency", receipt.get("currency") or "UGX"],
    ]
    if receipt.get("landlord_name"):
        pay_rows.insert(0, ["Received by", receipt.get("landlord_name")])
    story.extend([_kv_table(pay_rows), Spacer(1, 0.35 * cm)])

    if receipt.get("tx_hash"):
        story.append(Paragraph("Digital verification", section))
        chain_rows = [
            ["Status", "Payment recorded on RentDirect UG"],
            ["Network", (receipt.get("network") or settings.sui_network or "Sui").title()],
            ["Transaction", receipt.get("tx_hash") or "—"],
        ]
        story.extend([_kv_table(chain_rows), Spacer(1, 0.3 * cm)])

    if receipt.get("tax_id") or receipt.get("vat_amount"):
        story.append(Paragraph("Tax information", section))
        tax_rows = [
            ["Tax reference", receipt.get("tax_id") or "—"],
            ["URA code", receipt.get("ura_compliance_code") or "—"],
            ["VAT", receipt.get("vat_display") or "—"],
        ]
        story.extend([_kv_table(tax_rows), Spacer(1, 0.3 * cm)])

    qr_row = Table(
        [
            [
                _qr_image(verify_url),
                Paragraph(
                    "<b>Verify this receipt</b><br/>"
                    "Scan the QR code to confirm authenticity on RentDirect UG.<br/><br/>"
                    "<font size='7' color='#64748b'>"
                    "This document is system-generated. Do not alter amounts or references. "
                    "For disputes, contact the issuer with your receipt number."
                    "</font>",
                    body,
                ),
            ]
        ],
        colWidths=[3.5 * cm, 11.5 * cm],
    )
    qr_row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.5, line),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend([qr_row, Spacer(1, 0.5 * cm)])

    support = settings.email_support_email or "support@rentdirect.ug"
    story.append(
        Paragraph(
            f"RentDirect UG · Rental payment records · Uganda<br/>"
            f"Customer support: {support}<br/>"
            f"Receipt {receipt.get('receipt_number', '')} · Issued {receipt.get('issued_at_label', '')}",
            fine,
        )
    )

    doc.build(story)


def _kv_table(rows: list[list[str]]) -> Table:
    dark = colors.HexColor("#0f172a")
    muted = colors.HexColor("#64748b")
    t = Table(rows, colWidths=[4.2 * cm, 10.8 * cm])
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), muted),
                ("TEXTCOLOR", (1, 0), (1, -1), dark),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e2e8f0")),
            ]
        )
    )
    return t
