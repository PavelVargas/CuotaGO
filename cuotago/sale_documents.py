"""Customer-facing sale documents. Never serialize the internal sale model.

The allowlisted immutable view below is shared by the receipt HTML and PDF.
Acquisition costs, investments, profit, margin, internal notes and void reasons
are deliberately not part of this interface.
"""
from dataclasses import dataclass
from io import BytesIO
from typing import Callable
from xml.sax.saxutils import escape


@dataclass(frozen=True)
class CustomerSaleReceipt:
    business_name: str
    code: str
    date: str
    buyer_name: str
    buyer_phone: str
    item_name: str
    item_description: str
    identifiers: tuple
    quantity: int
    unit_price: str
    total: str
    payment_method: str
    reference: str
    voided: bool
    photo_url: str = ""


def customer_sale_receipt(sale, *, business_name: str, money: Callable,
                          payment_method_label: Callable, photo_url: str = "") -> CustomerSaleReceipt:
    """Explicit customer allowlist; adding an ORM field cannot leak it here."""
    asset = sale.asset
    vehicle = asset.kind in {"car", "motorcycle"}
    identifiers = []
    for label, value in (
        ("Placa" if vehicle else "Identificador", asset.identifier),
        ("Chasis / VIN" if vehicle else "Serial", asset.serial_number),
        ("Año", asset.vehicle_year if vehicle else None),
    ):
        if value is not None and str(value).strip():
            identifiers.append((label, str(value)))
    if vehicle and asset.mileage is not None:
        identifiers.append(("Kilometraje", f"{asset.mileage:,} km"))
    client = sale.client
    return CustomerSaleReceipt(
        business_name=business_name or "CuotaGo",
        code=sale.code or f"CGV-{sale.organization_id}-{sale.id:06d}",
        date=sale.sale_date.strftime("%d/%m/%Y"),
        # Prefer the buyer captured at the time of sale to mutable client data.
        buyer_name=sale.buyer_name or (client.full_name if client else "Cliente ocasional"),
        buyer_phone=sale.buyer_phone or (client.phone if client else "") or "",
        item_name=asset.name,
        item_description=" · ".join(str(v) for v in (asset.brand, asset.model) if v),
        identifiers=tuple(identifiers), quantity=int(sale.quantity or 1),
        unit_price=money(sale.unit_price), total=money(sale.total_amount),
        payment_method=payment_method_label(sale.payment_method),
        reference=sale.reference or "", voided=sale.status == "voided",
        photo_url=photo_url,
    )


def sale_receipt_pdf_bytes(receipt: CustomerSaleReceipt, *, photo: bytes | None = None) -> bytes:
    """Generate a real PDF from the customer view, not a print of internal HTML."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ink = colors.HexColor("#17283F")
    muted = colors.HexColor("#66758B")
    blue = colors.HexColor("#2468DD")
    line = colors.HexColor("#E1E8F1")
    pale = colors.HexColor("#F4F7FC")
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=42, leftMargin=42,
        topMargin=36, bottomMargin=44, title=f"Comprobante de venta {receipt.code}",
        author=receipt.business_name, subject="Comprobante para el cliente", pageCompression=1)
    width = A4[0] - 84
    body = ParagraphStyle("receipt-body", fontName="Helvetica", fontSize=10, leading=14, textColor=ink)
    small = ParagraphStyle("receipt-small", parent=body, fontSize=8, leading=11, textColor=muted)
    title = ParagraphStyle("receipt-title", parent=body, fontName="Helvetica-Bold", fontSize=22, leading=26)
    heading = ParagraphStyle("receipt-heading", parent=body, fontName="Helvetica-Bold", fontSize=12, leading=17)
    right = ParagraphStyle("receipt-right", parent=body, alignment=TA_RIGHT)
    amount = ParagraphStyle("receipt-amount", parent=right, fontName="Helvetica-Bold", fontSize=24, leading=29, textColor=blue)
    def p(value, style=body):
        # User-provided names and references are plain text, never ReportLab XML.
        return Paragraph(escape(str(value or "")).replace("\n", "<br/>"), style)
    def table(rows, widths, *, shaded=False, ruled=False):
        t = Table(rows, colWidths=widths, hAlign="LEFT")
        commands = [("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 12), ("RIGHTPADDING", (0,0), (-1,-1), 12),
            ("TOPPADDING", (0,0), (-1,-1), 10), ("BOTTOMPADDING", (0,0), (-1,-1), 10)]
        if shaded: commands += [("BACKGROUND", (0,0), (-1,-1), pale)]
        if ruled: commands += [("LINEBELOW", (0,0), (-1,-1), .45, line)]
        t.setStyle(TableStyle(commands))
        return t
    story = [p(receipt.business_name, title), Spacer(1,7),
        p("COMPROBANTE DE VENTA", ParagraphStyle("receipt-kicker", parent=small, textColor=blue)),
        Spacer(1,16), table([[p(receipt.code,heading),p(receipt.date,right)]], [width*.65,width*.35], shaded=True), Spacer(1,18)]
    if receipt.voided:
        story.extend([p("ANULADO", ParagraphStyle("receipt-void", parent=heading, textColor=colors.HexColor("#B43440"))),
            p("Esta venta fue anulada. Este documento no acredita un pago vigente.", small), Spacer(1,14)])
    story.extend([p("Comprador",small), p(receipt.buyer_name,heading)])
    if receipt.buyer_phone: story.append(p(receipt.buyer_phone,small))
    story.extend([Spacer(1,18), p("Detalle de la venta",heading), Spacer(1,9)])
    item = [p(receipt.item_name,heading)]
    if receipt.item_description: item.append(p(receipt.item_description,small))
    for label, value in receipt.identifiers: item.append(p(f"{label}: {value}",small))
    picture = None
    if photo:
        # Resample from validated inventory data, strip metadata, retain proportions.
        try:
            from PIL import Image as PILImage, ImageOps
            with PILImage.open(BytesIO(photo)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((560,380))
                image_bytes = BytesIO()
                image.save(image_bytes, format="JPEG", quality=82, optimize=True)
                iw, ih = image.size
            scale = min(160 / iw, 112 / ih)
            image_bytes.seek(0)
            picture = Image(image_bytes, width=iw*scale, height=ih*scale)
            picture.hAlign = "CENTER"
        except (OSError, ValueError):
            picture = None
    if picture:
        story.append(table([[picture,item]], [184,width-184], shaded=True))
    else:
        story.append(table([[item]], [width], shaded=True))
    story.extend([Spacer(1,13),table([
        [p("Cantidad",small),p("Precio unitario",small),p("Importe",ParagraphStyle("rh",parent=small,alignment=TA_RIGHT))],
        [p(str(receipt.quantity)),p(receipt.unit_price),p(receipt.total,right)]
    ],[width*.20,width*.37,width*.43],ruled=True),Spacer(1,14)])
    payment_rows = [[p("Método de pago",small),p(receipt.payment_method,right)]]
    if receipt.reference: payment_rows.append([p("Referencia",small),p(receipt.reference,right)])
    story.extend([table(payment_rows,[width*.30,width*.70],ruled=True),Spacer(1,16),
        table([[p("TOTAL DE LA VENTA" if receipt.voided else "TOTAL PAGADO",heading),p(receipt.total,amount)]],
            [width*.42,width*.58],shaded=True),Spacer(1,12)])
    if not receipt.voided:
        story.append(p("Pago completo registrado. Gracias por su compra.",small))
    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(line);canvas.line(42,36,A4[0]-42,36)
        canvas.setFillColor(muted);canvas.setFont("Helvetica",8)
        canvas.drawString(42,23,"Comprobante de venta | CuotaGo")
        canvas.drawRightString(A4[0]-42,23,f"Página {document.page}")
        canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()
