"""Small, dependency-light PDF documents for statements and payment receipts.

ReportLab imports stay inside the public functions so the application can still
start with a clear route-level error if a deployment forgot the dependency.
"""
from __future__ import annotations

from html import escape
from io import BytesIO


def _safe(value) -> str:
    return escape(str(value or "—"))


def statement_pdf_bytes(*, app_name, business_name, client, contracts, payments, totals, next_item, money, payment_method_label):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Estado de cuenta - {client.full_name}",
        author=business_name or app_name,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#344054"))
    small = ParagraphStyle("small", parent=body, fontSize=7.2, leading=9, textColor=colors.HexColor("#667085"))
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=21, textColor=colors.HexColor("#101828"), spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.HexColor("#101828"), spaceBefore=10, spaceAfter=5)
    right = ParagraphStyle("right", parent=body, alignment=TA_RIGHT)
    right_small = ParagraphStyle("right_small", parent=small, alignment=TA_RIGHT)

    story = []
    header = Table([
        [Paragraph(f"<b>{_safe(business_name or app_name)}</b>", body), Paragraph(f"<b>{_safe(client.full_name)}</b>", right)],
        [Paragraph("Estado de cuenta", h1), Paragraph(_safe(client.phone or "Sin teléfono"), right_small)],
    ], colWidths=[105 * mm, 57 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#D0D5DD")),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    story.extend([header, Spacer(1, 7)])

    summary_data = [[
        Paragraph("TOTAL ACORDADO", small), Paragraph("TOTAL RECIBIDO", small),
        Paragraph("SALDO PENDIENTE", small), Paragraph("MORA PENDIENTE", small),
    ], [
        Paragraph(f"<b>{_safe(money(totals['agreed']))}</b>", body),
        Paragraph(f"<b>{_safe(money(totals['paid']))}</b>", body),
        Paragraph(f"<b>{_safe(money(totals['balance']))}</b>", body),
        Paragraph(f"<b>{_safe(money(totals['late_fee']))}</b>", body),
    ]]
    summary = Table(summary_data, colWidths=[40.5 * mm] * 4)
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4E7EC")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#EAECF0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(summary)

    if next_item:
        story.extend([
            Spacer(1, 7),
            Paragraph(
                f"Próximo pago: <b>{_safe(money(next_item.remaining))}</b> - {next_item.due_date.strftime('%d/%m/%Y')}",
                body,
            ),
        ])

    story.append(Paragraph("Acuerdos", h2))
    contract_rows = [[Paragraph("Acuerdo / artículo", small), Paragraph("Estado", small), Paragraph("Pagado", right_small), Paragraph("Saldo", right_small)]]
    for contract in contracts:
        contract_rows.append([
            Paragraph(f"<b>{_safe(contract.code)}</b><br/><font size='7'>{_safe(contract.asset.name)}</font>", body),
            Paragraph(_safe({"active":"Activo","completed":"Completado","cancelled":"Anulado","voided":"Anulado"}.get(contract.status, contract.status)), small),
            Paragraph(_safe(money(contract.paid_total)), right),
            Paragraph(_safe(money(contract.balance)), right),
        ])
    if len(contract_rows) == 1:
        contract_rows.append([Paragraph("Sin acuerdos registrados.", body), "", "", ""])
    contracts_table = Table(contract_rows, colWidths=[73 * mm, 29 * mm, 30 * mm, 30 * mm], repeatRows=1)
    contracts_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, colors.HexColor("#EAECF0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(contracts_table)

    story.append(Paragraph("Pagos", h2))
    payment_rows = [[Paragraph("Recibo", small), Paragraph("Acuerdo", small), Paragraph("Fecha", small), Paragraph("Método", small), Paragraph("Monto", right_small)]]
    for payment in payments:
        receipt_code = payment.receipt_code or f"CGP-{payment.contract.organization_id}-{payment.id:06d}"
        payment_rows.append([
            Paragraph(_safe(receipt_code), body), Paragraph(_safe(payment.contract.code), body),
            Paragraph(payment.paid_at.strftime("%d/%m/%Y"), small), Paragraph(_safe(payment_method_label(payment.method)), small),
            Paragraph(_safe(money(payment.amount)), right),
        ])
    if len(payment_rows) == 1:
        payment_rows.append([Paragraph("Sin pagos registrados.", body), "", "", "", ""])
    payments_table = Table(payment_rows, colWidths=[38 * mm, 31 * mm, 28 * mm, 30 * mm, 35 * mm], repeatRows=1)
    payments_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, colors.HexColor("#EAECF0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(payments_table)
    story.extend([Spacer(1, 12), Paragraph(f"Documento generado por {_safe(app_name)}.", small)])

    doc.build(story)
    return buffer.getvalue()


def receipt_pdf_bytes(*, app_name, business_name, payment, registered_by, money, payment_method_label):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    contract = payment.contract
    receipt_code = payment.receipt_code or f"CGP-{contract.organization_id}-{payment.id:06d}"
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=25 * mm,
        leftMargin=25 * mm,
        topMargin=24 * mm,
        bottomMargin=24 * mm,
        title=f"Recibo {receipt_code}",
        author=business_name or app_name,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#344054"))
    muted = ParagraphStyle("muted", parent=body, fontSize=7.5, leading=9, textColor=colors.HexColor("#667085"))
    center = ParagraphStyle("center", parent=body, alignment=TA_CENTER)
    center_big = ParagraphStyle("center_big", parent=center, fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=colors.HexColor("#101828"))
    right = ParagraphStyle("right", parent=body, alignment=TA_RIGHT)

    payment_kind_label = "Inicial" if payment.payment_kind == "down_payment" else ("Abono" if payment.payment_kind == "advance" else "Pago")
    story = [
        Paragraph(f"<b>{_safe(business_name or app_name)}</b>", center),
        Spacer(1, 5),
        Paragraph(f"RECIBO DE {_safe(payment_kind_label).upper()}", ParagraphStyle("eyebrow", parent=muted, alignment=TA_CENTER)),
        Paragraph(_safe(money(payment.amount)), center_big),
        Paragraph(_safe(receipt_code), ParagraphStyle("code", parent=muted, alignment=TA_CENTER)),
        Spacer(1, 14),
    ]

    rows = [
        ("Cliente", contract.client.full_name),
        ("Acuerdo", contract.code),
        ("Artículo", contract.asset.name),
        ("Fecha", payment.paid_at.strftime("%d/%m/%Y %H:%M")),
        ("Método", payment_method_label(payment.method)),
    ]
    if registered_by:
        rows.append(("Registrado por", registered_by.name))
    if payment.reference:
        rows.append(("Referencia", payment.reference))
    if payment.late_fee_amount and payment.late_fee_amount > 0:
        rows.append(("Incluye mora", money(payment.late_fee_amount)))
    rows.append(("Saldo pendiente", money(contract.balance)))

    detail_rows = [[Paragraph(_safe(label), muted), Paragraph(f"<b>{_safe(value)}</b>", right)] for label, value in rows]
    details = Table(detail_rows, colWidths=[55 * mm, 85 * mm])
    details.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#EAECF0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(details)
    if payment.note:
        story.extend([Spacer(1, 10), Paragraph(f"Nota: {_safe(payment.note)}", body)])
    story.extend([Spacer(1, 18), Paragraph(f"Gracias por su pago - {_safe(app_name)}", ParagraphStyle("footer", parent=muted, alignment=TA_CENTER))])
    doc.build(story)
    return buffer.getvalue()
