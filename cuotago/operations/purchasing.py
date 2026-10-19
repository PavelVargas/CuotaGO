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


def _prepare_lines(s, org, rows, draft=False, old_lines=None):
    if len(rows) > 100 or (not rows and not draft):
        raise ValueError('Agrega entre 1 y 100 productos para confirmar.')
    prepared = []
    old_lines = old_lines or {}
    used_ids = set()
    kinds = {'car', 'motorcycle', 'phone', 'computer', 'appliance', 'other', 'otro'}
    for row in rows:
        old = None
        if row.get('line_id'):
            old_id = integer(row['line_id'])
            old = old_lines.get(old_id)
            if old is None or old_id in used_ids:
                raise ValueError('La linea no pertenece a este borrador o esta repetida.')
            used_ids.add(old_id)
        qty = integer(row.get('quantity') or (1 if draft else ''))
        cost = money(row.get('unit_cost') or 0) if draft else positive_money(row.get('unit_cost'))
        if cost < 0:
            raise ValueError('El costo no puede ser negativo.')
        money(cost * qty)
        asset = scoped(s, Asset, org, integer(row['asset_id'])) if row.get('asset_id') else None
        name = asset.name if asset else (row.get('name') or '').strip()
        kind = asset.kind if asset else row.get('kind', 'other')
        if not 2 <= len(name) <= 140:
            raise ValueError('Escribe un nombre de producto entre 2 y 140 caracteres.')
        if kind not in kinds:
            raise ValueError('Tipo de producto no valido.')
        if asset is not None and asset.is_virtual:
            raise ValueError('Un saldo inicial no es un producto de inventario.')
        photo_data, photo_mime = None, None
        # Retain an uploaded photo only for the same line/product. Never accept a
        # client-supplied URL, MIME type or arbitrary bytes as a trusted photo.
        if old is not None and old.asset_id == (asset.id if asset else None):
            photo_data, photo_mime = old.photo_data, old.photo_mime
        if asset is not None and not photo_data and photo_mime is None:
            photo_data = asset.image_thumb_data or asset.image_data
            photo_mime = asset.image_mime if photo_data else None
        if row.get('clear_photo'):
            photo_data, photo_mime = None, ''
        if row.get('photo'):
            photo_data, photo_mime = row['photo']
        prepared.append(dict(asset=asset, name=name, kind=kind, quantity=qty,
            received=0, unit_cost=cost, photo_data=photo_data, photo_mime=photo_mime))
    money(sum((r['unit_cost'] * r['quantity'] for r in prepared), Decimal('0')))
    return prepared


def create_order(s, org, actor, supplier_id, rows, reference='', expected_on=None, note='', state='sent'):
    if state not in {'draft', 'sent'}:
        raise ValueError('Estado de orden no valido.')
    supplier = scoped(s, Supplier, org, supplier_id)
    prepared = _prepare_lines(s, org, rows, draft=state == 'draft')
    order = PurchaseOrder(organization_id=org, supplier_id=supplier.id,
        reference=reference[:120], expected_on=expected_on, note=note[:240],
        created_by_user_id=actor, state=state, revision=1)
    s.add(order)
    for data in prepared:
        order.lines.append(PurchaseOrderLine(**data))
    s.flush()
    audit(s, org, actor, 'order.draft_saved' if state == 'draft' else 'order.created',
          'purchase_order', order.id, 'Borrador guardado.' if state == 'draft' else
          'Orden confirmada; inventario sin cambios.', order_totals(order))
    return order


def update_draft(s, org, actor, order_id, revision, supplier_id, rows,
                 reference='', expected_on=None, note='', confirm=False):
    order = scoped(s, PurchaseOrder, org, order_id, lock=True)
    s.refresh(order, ['lines'])
    if order.state != 'draft':
        raise ValueError('Solo se pueden editar borradores. Esta orden ya cambio de estado.')
    if order.revision != integer(revision):
        raise ValueError('Otra ventana modifico el borrador. Recargalo antes de guardar.')
    supplier = scoped(s, Supplier, org, supplier_id)
    prepared = _prepare_lines(s, org, rows, draft=not confirm,
                             old_lines={line.id: line for line in order.lines})
    # Validation completes before replacing anything. The surrounding request
    # owns the transaction and rolls it all back on any error.
    for old in list(order.lines):
        order.lines.remove(old)
        s.delete(old)
    s.flush()
    order.supplier = supplier
    order.reference, order.expected_on, order.note = reference[:120], expected_on, note[:240]
    for data in prepared:
        order.lines.append(PurchaseOrderLine(**data))
    order.state = 'sent' if confirm else 'draft'
    order.revision += 1
    s.flush()
    audit(s, org, actor, 'order.confirmed' if confirm else 'order.draft_saved',
          'purchase_order', order.id, 'Orden confirmada.' if confirm else 'Borrador actualizado.',
          {'revision': order.revision, **order_totals(order)})
    return order


def discard_draft(s, org, actor, order_id, revision):
    order = scoped(s, PurchaseOrder, org, order_id, lock=True)
    if order.state != 'draft' or order.revision != integer(revision):
        raise ValueError('El borrador cambio. Recarga antes de descartarlo.')
    order.state = 'discarded'
    order.revision += 1
    audit(s, org, actor, 'order.discarded', 'purchase_order', order.id,
          'Borrador descartado; sin movimientos de inventario ni dinero.')
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
                acquisition_date=business_date(utcnow(), zone),
                image_data=line.photo_data, image_thumb_data=line.photo_data,
                image_mime=line.photo_mime or None, image_updated_at=utcnow() if line.photo_data else None)
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
    if order.state in {'draft', 'discarded'}:
        raise ValueError('Confirma la orden antes de registrar un pago al proveedor.')
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
