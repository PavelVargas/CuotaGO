"""Purchase orders do not change stock; only a confirmed partial receipt does."""
from decimal import Decimal
import uuid
from ..models import Asset, Purchase, Supplier
from ..business_time import utcnow, business_date
from ..money_ops import money, integer, positive_money, receive_stock
from .models import PurchaseOrder, PurchaseOrderLine, OrderReceipt, SupplierPayment
from .common import scoped, audit
from .cash import post_entry, reverse_entry, METHODS


def order_totals(order):
    ordered = sum((money(l.unit_cost * l.quantity) for l in order.lines), Decimal('0.00'))
    received = sum((money(l.unit_cost * l.received) for l in order.lines), Decimal('0.00'))
    paid = sum((money(p.amount) for p in order.payments if not p.voided_at), Decimal('0.00'))
    return {'ordered': ordered, 'received': received, 'paid': paid,
            'payable': max(received - paid, Decimal('0.00')),
            'advance': max(paid - received, Decimal('0.00')),
            'pending_units': sum(l.quantity - l.received for l in order.lines)}


def create_order(s, org, actor, supplier_id, rows, reference='', expected_on=None, note=''):
    supplier = scoped(s, Supplier, org, supplier_id)
    if not rows or len(rows) > 100:
        raise ValueError('Agrega entre 1 y 100 articulos.')
    order = PurchaseOrder(organization_id=org, supplier_id=supplier.id,
        reference=reference[:120], expected_on=expected_on, note=note[:240],
        created_by_user_id=actor, state='sent')
    s.add(order)
    for row in rows:
        qty = integer(row.get('quantity'))
        cost = positive_money(row.get('unit_cost'))
        money(cost * qty)
        asset_id = row.get('asset_id')
        asset = scoped(s, Asset, org, integer(asset_id)) if asset_id else None
        name = asset.name if asset else (row.get('name') or '').strip()
        kind = asset.kind if asset else row.get('kind', 'other')
        if len(name) < 2 or len(name) > 140:
            raise ValueError('Escribe un nombre de articulo entre 2 y 140 caracteres.')
        if kind not in {'car', 'motorcycle', 'phone', 'computer', 'appliance', 'other'}:
            raise ValueError('Tipo de articulo no valido.')
        if asset is not None and asset.is_virtual:
            raise ValueError('Un saldo inicial no es un articulo de inventario.')
        order.lines.append(PurchaseOrderLine(asset=asset, name=name, kind=kind,
                         quantity=qty, received=0, unit_cost=cost))
    s.flush()
    money(order_totals(order)['ordered'])
    audit(s, org, actor, 'order.created', 'purchase_order', order.id,
          'Orden de compra creada; inventario sin cambios.', order_totals(order))
    return order


def receive_order(s, org, actor, order_id, quantities, zone):
    order = scoped(s, PurchaseOrder, org, order_id, lock=True)
    s.refresh(order, ['lines'])
    if order.state not in {'sent', 'partial'}:
        raise ValueError('Esta orden ya no admite recepciones.')
    line_ids = {str(l.id) for l in order.lines}
    if set(quantities) - line_ids:
        raise ValueError('La recepcion contiene una linea ajena a la orden.')
    prepared = []
    for line in order.lines:
        qty = integer(quantities.get(str(line.id), 0), 0)
        if qty > line.quantity - line.received:
            raise ValueError(f'La cantidad supera lo pendiente de {line.name}.')
        if qty:
            prepared.append((line, qty))
    if not prepared:
        raise ValueError('Indica al menos una unidad recibida.')
    # Order lock -> assets in ascending order; nothing takes these in reverse order.
    locked = {identifier: scoped(s, Asset, org, identifier, lock=True)
              for identifier in sorted({l.asset_id for l, _ in prepared if l.asset_id})}
    batch_key = str(uuid.uuid4())
    for line, qty in prepared:
        if line.asset_id:
            asset = locked[line.asset_id]
            s.expire(asset, ['contracts', 'sales'])
            receive_stock(asset, qty, line.unit_cost)
        else:
            asset = Asset(organization_id=org, name=line.name, kind=line.kind,
                estimated_value=line.unit_cost, sale_price=0, quantity_total=qty, status='available',
                acquisition_type='purchase', acquisition_origin=order.supplier.name,
                acquisition_date=business_date(utcnow(), zone))
            s.add(asset)
            s.flush()
            line.asset_id = asset.id
        if asset.status not in {'workshop', 'maintenance'}:
            asset.status = 'available' if asset.available_quantity > 0 else asset.status
        purchase = Purchase(organization_id=org, asset=asset, supplier_id=order.supplier_id,
            supplier=order.supplier.name, batch_key=batch_key, reference=order.reference,
            purchase_date=business_date(utcnow(), zone), quantity=qty, unit_cost=line.unit_cost,
            notes=f'Recepcion de orden OC-{order.id}; no equivale a pago al proveedor.')
        s.add(purchase)
        s.flush()
        s.add(OrderReceipt(order_id=order.id, line_id=line.id, purchase_id=purchase.id,
                         quantity=qty, actor_id=actor))
        line.received += qty
    order.state = 'received' if all(l.received == l.quantity for l in order.lines) else 'partial'
    audit(s, org, actor, 'order.received', 'purchase_order', order.id,
          'Recepcion de mercancia confirmada.', {'quantities': quantities, 'batch_key': batch_key})
    return order


def pay_supplier(s, org, actor, order_id, amount, method, reference=''):
    order = scoped(s, PurchaseOrder, org, order_id, lock=True)
    s.refresh(order, ['payments', 'lines'])
    if order.state == 'cancelled':
        limit = order_totals(order)['received']
    else:
        limit = order_totals(order)['ordered']
    amount = positive_money(amount)
    if amount + order_totals(order)['paid'] > limit:
        raise ValueError('El pago supera el total autorizado de la orden.')
    if method not in METHODS:
        raise ValueError('Medio de pago no valido.')
    payment = SupplierPayment(organization_id=org, order=order, amount=amount,
        method=method, reference=reference[:120], actor_id=actor)
    s.add(payment)
    s.flush()
    post_entry(s, org, actor, 'supplier_payment', payment.id, -amount, method,
               f'Pago a proveedor de orden OC-{order.id}', reference)
    audit(s, org, actor, 'supplier.paid', 'supplier_payment', payment.id,
          'Pago a proveedor registrado.', {'amount': amount, 'order_id': order.id})
    return payment


def void_supplier_payment(s, org, actor, payment_id, reason):
    ref = scoped(s, SupplierPayment, org, payment_id)
    order = scoped(s, PurchaseOrder, org, ref.order_id, lock=True)
    payment = scoped(s, SupplierPayment, org, payment_id, lock=True)
    if payment.voided_at:
        raise ValueError('El pago ya esta revertido.')
    if len((reason or '').strip()) < 5:
        raise ValueError('Escribe el motivo de la correccion.')
    payment.voided_at, payment.void_reason = utcnow(), reason[:240]
    reverse_entry(s, org, actor, 'supplier_reversal', payment.id, 'supplier_payment', payment.id, payment.amount, payment.method,
               f'Reversion de pago a proveedor {payment.id}', payment.reference)
    audit(s, org, actor, 'supplier.reversed', 'supplier_payment', payment.id,
          'Pago a proveedor revertido.', {'reason': reason})
    return payment


def cancel_order(s, org, actor, order_id, reason):
    order = scoped(s, PurchaseOrder, org, order_id, lock=True)
    s.refresh(order, ['payments', 'lines'])
    if order.state not in {'sent', 'partial'}:
        raise ValueError('Solo se cancela la parte pendiente de una orden abierta.')
    if len((reason or '').strip()) < 5:
        raise ValueError('Escribe un motivo para cancelar el remanente.')
    if order_totals(order)['advance'] > 0:
        raise ValueError('Existe un anticipo pendiente. Concilia o revierte el anticipo antes de cancelar.')
    order.state = 'cancelled'
    audit(s, org, actor, 'order.cancelled', 'purchase_order', order.id,
          'Remanente de orden cancelado; recepciones y pagos conservados.', {'reason': reason[:240]})
    return order
