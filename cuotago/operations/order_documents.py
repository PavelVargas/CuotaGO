"""Read-only purchase/receipt documents. A plan is never presented as a receipt."""
from collections import OrderedDict
from ..models import Purchase
from .models import OrderReceipt, PurchaseOrder
from .common import scoped

STATE_LABELS = {'draft': 'Borrador', 'sent': 'Confirmada', 'partial': 'Recepción parcial',
                'received': 'Recibida', 'cancelled': 'Cancelada', 'discarded': 'Descartada'}


def receipt_batches(s, org, order_id):
    scoped(s, PurchaseOrder, org, order_id)
    rows = (s.query(OrderReceipt, Purchase)
        .join(Purchase, OrderReceipt.purchase_id == Purchase.id)
        .filter(OrderReceipt.order_id == order_id, Purchase.organization_id == org)
        .order_by(OrderReceipt.id).all())
    groups = OrderedDict()
    for receipt, purchase in rows:
        key = purchase.batch_key or f'legacy-{receipt.id}'
        group = groups.setdefault(key, dict(id=receipt.id, code=f'RC-{receipt.id:06d}',
            date=receipt.received_at, units=0, entries=[]))
        group['units'] += receipt.quantity
        group['entries'].append(dict(line_id=receipt.line_id, quantity=receipt.quantity))
    return list(reversed(list(groups.values())))


def receipt_document(s, org, order_id, receipt_id):
    groups = receipt_batches(s, org, order_id)
    for group in groups:
        if group['id'] == receipt_id:
            return group
    raise LookupError('Recepcion no encontrada en esta orden.')
