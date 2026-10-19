import json
import hashlib
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for, Response, jsonify
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from ..extensions import db
from ..models import Client, Contract, Payment, Supplier, Asset, User
from ..permissions import has_permission, permission_required
from ..business_time import utcnow
from ..money_ops import money, integer
from ..transactions import lock_contract
from ..security_primitives import new_token, digest
from .models import (CashShift, CashRegister, MoneyEntry, PurchaseOrder, PurchaseOrderLine, SupplierPayment,
                     PortalGrant, ImportBatch, BankLine, OrganizationControls)
from .common import operation, scoped, audit
from .http import validated_operation, payload
from .cash import open_shift, close_shift, expected_cash
from .payments import reverse_payment
from .purchasing import create_order, receive_order, pay_supplier, order_totals, cancel_order, void_supplier_payment, update_draft, discard_draft
from .order_documents import STATE_LABELS, receipt_batches, receipt_document
from .order_images import normalize_photo, MAX_PHOTO_BYTES
from .importing import preview_import, apply_import, match_bank_line, COLUMNS

ops_bp = Blueprint('ops', __name__, url_prefix='/operations')


def org():
    return current_user.organization_id


def zone():
    return current_app.config.get('APP_TIMEZONE', 'America/Santo_Domingo')


def begin(scope, identifier=None):
    return operation(db.session, org(), scope, request.form.get('request_key', ''),
                     {'id': identifier, 'form': payload()})


@ops_bp.before_request
@login_required
def check_available():
    if not current_app.config.get('OPERATIONS_ENABLED', True):
        abort(404)


@ops_bp.get('/')
def index():
    return render_template('operations/index.html')


@ops_bp.get('/cash')
@permission_required('cash.own')
def cash():
    mine = CashShift.query.filter_by(organization_id=org(), user_id=current_user.id)
    active = mine.filter_by(closed_at=None).order_by(CashShift.id.desc()).first()
    q = CashShift.query.filter_by(organization_id=org())
    entries = MoneyEntry.query.filter_by(organization_id=org())
    if not has_permission(current_user, 'cash.manage'):
        q = q.filter_by(user_id=current_user.id)
        own_shifts = db.session.query(CashShift.id).filter_by(organization_id=org(), user_id=current_user.id)
        entries = entries.filter(or_(MoneyEntry.actor_id == current_user.id, MoneyEntry.cash_shift_id.in_(own_shifts)))
    page = q.order_by(CashShift.id.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=25, error_out=False)
    if active:
        entries = entries.filter_by(cash_shift_id=active.id)
    return render_template('operations/cash.html', active=active,
        expected=expected_cash(db.session, active) if active else 0,
        page=page, entries=entries.order_by(MoneyEntry.id.desc()).limit(100).all())


@ops_bp.post('/cash/open')
@permission_required('cash.own')
@validated_operation
def cash_open():
    op, replay = begin('cash_open')
    if not replay:
        item = open_shift(db.session, org(), current_user.id, request.form.get('opening'))
        op.result_id = str(item.id)
        db.session.commit()
    return redirect(url_for('ops.cash'))


@ops_bp.post('/cash/<int:shift_id>/close')
@permission_required('cash.own')
@validated_operation
def cash_close(shift_id):
    op, replay = begin('cash_close', shift_id)
    if not replay:
        item = close_shift(db.session, org(), current_user.id, shift_id,
            request.form.get('counted'), request.form.get('note'), has_permission(current_user, 'cash.manage'))
        op.result_id = str(item.id)
        db.session.commit()
        flash('Caja cerrada. El arqueo queda congelado; las correcciones se registran como nuevos movimientos.', 'success')
    return redirect(url_for('ops.cash'))


@ops_bp.get('/payments/<int:payment_id>/reverse')
@permission_required('payments.reverse')
@validated_operation
def reversal_form(payment_id):
    payment = Payment.query.join(Contract).filter(Payment.id == payment_id, Contract.organization_id == org()).first_or_404()
    return render_template('operations/reversal.html', payment=payment)


@ops_bp.post('/payments/<int:payment_id>/reverse')
@permission_required('payments.reverse')
@validated_operation
def reversal_create(payment_id):
    op, replay = begin('payment_reverse', payment_id)
    if not replay:
        payment = Payment.query.join(Contract).filter(Payment.id == payment_id, Contract.organization_id == org()).first_or_404()
        contract = lock_contract(payment.contract_id)
        from ..main import sync_contract_late_fees
        sync_contract_late_fees(contract, commit=False, already_locked=True)
        reversal = reverse_payment(db.session, org(), current_user.id, contract, payment_id, request.form.get('reason'), zone())
        op.result_id = str(reversal.id)
        from ..main import refresh_asset_status
        refresh_asset_status(contract.asset)
        db.session.commit()
        flash('Reversion registrada. No se realizo ninguna transferencia bancaria ni se borro el pago original.', 'success')
    return redirect(url_for('main.payment_receipt', payment_id=payment_id))


def _asset_summary(item):
    return dict(id=item.id, name=item.name, kind=item.kind,
        cost=str(item.estimated_value or 0), year=item.vehicle_year,
        identifier=item.identifier or item.serial_number or '',
        photo=url_for('ops.order_asset_photo', asset_id=item.id) if item.image_mime else '')


def _editor_context(order=None, rows=None):
    if rows is None:
        rows = [dict(line_id=line.id, key=uuid.uuid4().hex, asset_id=line.asset_id or '',
            name=line.name, kind=line.kind, quantity=line.quantity, unit_cost=str(line.unit_cost),
            photo=url_for('ops.order_line_photo', order_id=order.id, line_id=line.id)
                if line.photo_mime or (line.photo_mime is None and line.asset and line.asset.image_mime) else '')
            for line in order.lines] if order else []
    return dict(order=order, editor_rows=rows,
        suppliers=Supplier.query.filter_by(organization_id=org()).order_by(Supplier.name).all(),
        assets=[_asset_summary(a) for a in Asset.query.filter_by(organization_id=org(), is_virtual=False)
                .order_by(Asset.name, Asset.id).limit(60).all()])


def _order_rows():
    fields = ['asset_id', 'name', 'kind', 'quantity', 'unit_cost']
    values = {key: request.form.getlist('line_' + key) for key in fields}
    count = len(values['quantity'])
    if count > 100 or not all(len(value) == count for value in values.values()):
        raise ValueError('Revisa las lineas. Se permiten hasta 100 productos por orden.')
    optional = {key: request.form.getlist('line_' + key) for key in ['id', 'key', 'clear_photo']}
    if any(value and len(value) != count for value in optional.values()):
        raise ValueError('El formulario tiene lineas incompletas. Recargalo.')
    rows, fingerprints, used_keys = [], {}, set()
    for i in range(count):
        row = {key: values[key][i] for key in fields}
        row['line_id'] = optional['id'][i] if optional['id'] else ''
        key = optional['key'][i] if optional['key'] else str(i)
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', key) or key in used_keys:
            raise ValueError('Identificador de linea no valido.')
        used_keys.add(key)
        row['clear_photo'] = bool(optional['clear_photo'] and optional['clear_photo'][i] == '1')
        upload = request.files.get('photo_' + key)
        if upload and upload.filename:
            raw = upload.read(MAX_PHOTO_BYTES + 1)
            row['photo'] = normalize_photo(raw)
            fingerprints[key] = hashlib.sha256(raw).hexdigest()
        # Empty no-JavaScript placeholder is not a product.
        if not row['asset_id'] and not row['name'].strip() and not row['unit_cost'].strip() and not upload:
            continue
        rows.append(row)
    return rows, fingerprints


def _order_saved(item, draft):
    target = url_for('ops.order_edit' if draft else 'ops.order_detail', order_id=item.id)
    if request.accept_mimetypes.best == 'application/json':
        return jsonify(ok=True, redirect=target)
    flash('Borrador guardado.' if draft else 'Orden confirmada.', 'success')
    return redirect(target, code=303)


def _order_error(error, item=None):
    db.session.rollback()
    if request.accept_mimetypes.best == 'application/json':
        return jsonify(ok=False, error=str(error)), 400
    # Non-JS clients keep typed fields; fresh uploads must be selected again.
    count = len(request.form.getlist('line_quantity'))
    rows = []
    for i in range(min(count, 100)):
        row = {'key': uuid.uuid4().hex, 'photo': ''}
        for key in ['id', 'asset_id', 'name', 'kind', 'quantity', 'unit_cost']:
            values = request.form.getlist('line_' + key)
            row['line_id' if key == 'id' else key] = values[i] if i < len(values) else ''
        rows.append(row)
    return render_template('operations/order_new.html', form_error=str(error),
        posted=request.form, **_editor_context(item, rows)), 400


@ops_bp.get('/orders')
@permission_required('purchases.view')
def orders():
    status = request.args.get('state', '')
    query = PurchaseOrder.query.filter_by(organization_id=org()).options(
        selectinload(PurchaseOrder.supplier), selectinload(PurchaseOrder.lines), selectinload(PurchaseOrder.payments))
    if status in STATE_LABELS:
        query = query.filter_by(state=status)
    else:
        query = query.filter(PurchaseOrder.state != 'discarded')
    page = query.order_by(PurchaseOrder.id.desc()).paginate(
        page=request.args.get('page', 1, type=int), per_page=25, error_out=False)
    return render_template('operations/orders.html', page=page, totals=order_totals,
                           state_labels=STATE_LABELS, selected_state=status)


@ops_bp.get('/orders/catalog')
@permission_required('purchases.manage')
def order_catalog():
    query = Asset.query.filter_by(organization_id=org(), is_virtual=False)
    term = (request.args.get('q') or '').strip()[:120]
    if term:
        # Escape wildcards: this is a literal search, not user-written SQL LIKE.
        pattern = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(*[column.ilike(pattern, escape='\\')
            for column in [Asset.name, Asset.brand, Asset.model, Asset.identifier, Asset.serial_number]]))
    page = query.order_by(Asset.name, Asset.id).paginate(page=max(1, request.args.get('page', 1, type=int)),
                                                       per_page=30, error_out=False)
    response = jsonify(items=[_asset_summary(a) for a in page.items], has_more=page.has_next, page=page.page)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@ops_bp.get('/orders/catalog/<int:asset_id>/photo')
@permission_required('purchases.view')
@validated_operation
def order_asset_photo(asset_id):
    asset = scoped(db.session, Asset, org(), asset_id)
    data = asset.image_thumb_data or asset.image_data
    if not data or asset.is_virtual:
        abort(404)
    return Response(data, mimetype=asset.image_mime or 'image/webp',
        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@ops_bp.route('/orders/new', methods=['GET', 'POST'])
@permission_required('purchases.manage')
@validated_operation
def order_new():
    if request.method == 'POST':
        try:
            action = request.form.get('intent') or request.form.get('action') or 'confirm'
            if action not in {'draft', 'confirm'}:
                raise ValueError('Accion de orden no valida.')
            rows, photos = _order_rows()
            op, replay = operation(db.session, org(), 'order_create', request.form.get('request_key', ''),
                                   {'form': payload(), 'photos': photos})
            if not replay:
                item = create_order(db.session, org(), current_user.id, integer(request.form.get('supplier_id')),
                    rows, request.form.get('reference', ''),
                    date.fromisoformat(request.form['expected_on']) if request.form.get('expected_on') else None,
                    request.form.get('note', ''), state='draft' if action == 'draft' else 'sent')
                op.result_id = str(item.id)
                db.session.commit()
            else:
                item = scoped(db.session, PurchaseOrder, org(), int(op.result_id))
            return _order_saved(item, item.state == 'draft')
        except ValueError as error:
            return _order_error(error)
    return render_template('operations/order_new.html', **_editor_context())


@ops_bp.route('/orders/<int:order_id>/edit', methods=['GET', 'POST'])
@permission_required('purchases.manage')
@validated_operation
def order_edit(order_id):
    item = scoped(db.session, PurchaseOrder, org(), order_id)
    if request.method == 'POST':
        try:
            action = request.form.get('intent') or request.form.get('action') or 'confirm'
            if action not in {'draft', 'confirm'}:
                raise ValueError('Accion de orden no valida.')
            rows, photos = _order_rows()
            op, replay = operation(db.session, org(), 'order_edit', request.form.get('request_key', ''),
                                   {'id': order_id, 'form': payload(), 'photos': photos})
            if not replay:
                item = update_draft(db.session, org(), current_user.id, order_id,
                    request.form.get('revision'), integer(request.form.get('supplier_id')),
                    rows, request.form.get('reference', ''),
                    date.fromisoformat(request.form['expected_on']) if request.form.get('expected_on') else None,
                    request.form.get('note', ''), confirm=action == 'confirm')
                op.result_id = str(item.id)
                db.session.commit()
            return _order_saved(item, item.state == 'draft')
        except ValueError as error:
            return _order_error(error, item)
    if item.state != 'draft':
        return redirect(url_for('ops.order_detail', order_id=item.id))
    return render_template('operations/order_new.html', **_editor_context(item))


@ops_bp.post('/orders/<int:order_id>/discard')
@permission_required('purchases.manage')
@validated_operation
def order_discard(order_id):
    op, replay = begin('order_discard', order_id)
    if not replay:
        item = discard_draft(db.session, org(), current_user.id, order_id, request.form.get('revision'))
        op.result_id = str(item.id)
        db.session.commit()
    flash('Borrador descartado.', 'success')
    return redirect(url_for('ops.orders'), code=303)


@ops_bp.get('/orders/<int:order_id>')
@permission_required('purchases.view')
@validated_operation
def order_detail(order_id):
    item = scoped(db.session, PurchaseOrder, org(), order_id)
    return render_template('operations/order_detail.html', order=item, totals=order_totals(item),
        state_labels=STATE_LABELS, receipts=receipt_batches(db.session, org(), order_id))


@ops_bp.get('/orders/<int:order_id>/lines/<int:line_id>/photo')
@permission_required('purchases.view')
@validated_operation
def order_line_photo(order_id, line_id):
    item = scoped(db.session, PurchaseOrder, org(), order_id)
    line = next((line for line in item.lines if line.id == line_id), None)
    if line is None:
        abort(404)
    data, mime = line.photo_data, line.photo_mime
    if not data and mime is None and line.asset and line.asset.organization_id == org():
        data, mime = line.asset.image_thumb_data or line.asset.image_data, line.asset.image_mime
    if not data:
        abort(404)
    return Response(data, mimetype=mime or 'image/webp',
        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


def _print_order(order_id, kind, receipt_id=None):
    item = scoped(db.session, PurchaseOrder, org(), order_id)
    if item.state in {'draft', 'discarded'}:
        raise ValueError('Confirma la orden antes de imprimir documentos de mercancia.')
    receipt = receipt_document(db.session, org(), order_id, receipt_id) if receipt_id else None
    quantities = {entry['line_id']: entry['quantity'] for entry in receipt['entries']} if receipt else None
    rows = [dict(line=line, quantity=quantities[line.id] if quantities else line.quantity)
            for line in item.lines if quantities is None or line.id in quantities]
    return render_template('operations/order_print.html', order=item, kind=kind,
        receipt=receipt, print_rows=rows, totals=order_totals(item), state_labels=STATE_LABELS,
        printed_at=utcnow())


@ops_bp.get('/orders/<int:order_id>/print')
@permission_required('purchases.view')
@validated_operation
def order_print(order_id):
    return _print_order(order_id, 'order')


@ops_bp.get('/orders/<int:order_id>/conduce')
@permission_required('purchases.view')
@validated_operation
def order_conduce(order_id):
    return _print_order(order_id, 'conduce')


@ops_bp.get('/orders/<int:order_id>/receipts/<int:receipt_id>/print')
@permission_required('purchases.view')
@validated_operation
def order_receipt_print(order_id, receipt_id):
    return _print_order(order_id, 'receipt', receipt_id)


@ops_bp.post('/orders/<int:order_id>/receive')
@permission_required('purchases.manage')
@validated_operation
def order_receive(order_id):
    op, replay = begin('order_receive', order_id)
    if not replay:
        quantities = {key[4:]: value for key, value in request.form.items() if key.startswith('qty_')}
        item = receive_order(db.session, org(), current_user.id, order_id, quantities, zone())
        op.result_id = str(item.id)
        db.session.commit()
        flash('Recepcion confirmada. Solo las unidades recibidas entraron al inventario.', 'success')
    return redirect(url_for('ops.order_detail', order_id=order_id))


@ops_bp.post('/orders/<int:order_id>/pay')
@permission_required('suppliers.pay')
@validated_operation
def order_pay(order_id):
    op, replay = begin('supplier_pay', order_id)
    if not replay:
        item = pay_supplier(db.session, org(), current_user.id, order_id,
            request.form.get('amount'), request.form.get('method'), request.form.get('reference', ''))
        op.result_id = str(item.id)
        db.session.commit()
    return redirect(url_for('ops.order_detail', order_id=order_id))


@ops_bp.post('/supplier-payments/<int:payment_id>/reverse')
@permission_required('suppliers.pay')
@validated_operation
def supplier_reverse(payment_id):
    item = scoped(db.session, SupplierPayment, org(), payment_id)
    op, replay = begin('supplier_reverse', payment_id)
    if not replay:
        void_supplier_payment(db.session, org(), current_user.id, payment_id, request.form.get('reason'))
        op.result_id = str(item.id)
        db.session.commit()
    return redirect(url_for('ops.order_detail', order_id=item.order_id))


@ops_bp.post('/orders/<int:order_id>/cancel')
@permission_required('purchases.manage')
@validated_operation
def order_cancel(order_id):
    op, replay = begin('order_cancel', order_id)
    if not replay:
        item = cancel_order(db.session, org(), current_user.id, order_id, request.form.get('reason'))
        op.result_id = str(item.id)
        db.session.commit()
    return redirect(url_for('ops.order_detail', order_id=order_id))


@ops_bp.route('/imports', methods=['GET', 'POST'])
@permission_required('data.import')
@validated_operation
def imports():
    if request.method == 'POST':
        upload = request.files.get('file')
        if not upload:
            raise ValueError('Selecciona un CSV para revisar.')
        batch, rows = preview_import(db.session, org(), current_user.id,
            request.form.get('kind'), upload.read(1024 * 1024 + 1), request.form.get('account', ''))
        db.session.commit()
        return render_template('operations/import_preview.html', batch=batch, rows=rows, columns=COLUMNS[batch.kind])
    return render_template('operations/imports.html', columns=COLUMNS)


@ops_bp.get('/imports/template/<kind>.csv')
@permission_required('data.import')
def import_template(kind):
    if kind not in COLUMNS:
        abort(404)
    return Response(','.join(COLUMNS[kind]) + '\r\n', mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="cuotago-{kind}.csv"', 'Cache-Control': 'private, no-store'})


@ops_bp.post('/imports/<int:batch_id>/confirm')
@permission_required('data.import')
@validated_operation
def import_confirm(batch_id):
    batch = apply_import(db.session, org(), current_user.id, batch_id, request.form.get('digest'), zone())
    db.session.commit()
    flash(f'Importacion aplicada: {batch.applied_count} registros. No se duplican al repetir la confirmacion.', 'success')
    return redirect(url_for('ops.bank' if batch.kind == 'bank' else 'main.clients'))


@ops_bp.get('/bank')
@permission_required('bank.reconcile')
def bank():
    page = BankLine.query.filter_by(organization_id=org()).order_by(BankLine.id.desc()).paginate(
        page=request.args.get('page', 1, type=int), per_page=25, error_out=False)
    entries = MoneyEntry.query.filter(MoneyEntry.organization_id == org(), MoneyEntry.method != 'cash').order_by(MoneyEntry.id.desc()).limit(100).all()
    return render_template('operations/bank.html', page=page, entries=entries)


@ops_bp.post('/bank/<int:bank_id>/match')
@permission_required('bank.reconcile')
@validated_operation
def bank_match(bank_id):
    op, replay = begin('bank_match', bank_id)
    if not replay:
        row = match_bank_line(db.session, org(), current_user.id, bank_id,
             integer(request.form.get('entry_id')), request.form.get('reason'), zone())
        op.result_id = str(row.id)
        db.session.commit()
    return redirect(url_for('ops.bank'))


@ops_bp.post('/bank/<int:bank_id>/unmatch')
@permission_required('bank.reconcile')
@validated_operation
def bank_unmatch(bank_id):
    row = scoped(db.session, BankLine, org(), bank_id, lock=True)
    reason = (request.form.get('reason') or '').strip()
    if not row.money_entry_id or len(reason) < 5:
        raise ValueError('Selecciona una coincidencia e indica el motivo para retirarla.')
    audit(db.session, org(), current_user.id, 'bank.unmatched', 'bank_line', row.id,
        'Coincidencia manual retirada.', {'entry': row.money_entry_id, 'reason': reason[:240]})
    row.money_entry_id = row.matched_by = row.matched_at = None
    db.session.commit()
    return redirect(url_for('ops.bank'))


@ops_bp.get('/collectors')
@permission_required('collectors.manage')
def collectors():
    q = Client.query.filter_by(organization_id=org())
    term = request.args.get('q', '').strip()[:120]
    if term:
        q = q.filter(Client.full_name.ilike('%' + term + '%'))
    page = q.order_by(Client.full_name).paginate(page=request.args.get('page', 1, type=int), per_page=25, error_out=False)
    people = User.query.filter_by(organization_id=org(), role='collector', is_enabled=True).order_by(User.name).all()
    return render_template('operations/collectors.html', page=page, people=people)


@ops_bp.post('/clients/<int:client_id>/assignment')
@permission_required('collectors.manage')
@validated_operation
def assignment(client_id):
    client = scoped(db.session, Client, org(), client_id, lock=True)
    user_id = request.form.get('collector_id')
    person = scoped(db.session, User, org(), integer(user_id)) if user_id else None
    if person is not None and (person.role != 'collector' or not person.is_enabled):
        raise ValueError('Selecciona un cobrador activo de este negocio.')
    old = client.assigned_collector_id
    client.assigned_collector_id = person.id if person else None
    audit(db.session, org(), current_user.id, 'client.assigned', 'client', client.id,
          'Cartera asignada.', {'old': old, 'new': client.assigned_collector_id})
    db.session.commit()
    return redirect(url_for('ops.collectors'))


@ops_bp.route('/clients/<int:client_id>/portal', methods=['GET', 'POST'])
@permission_required('portal.manage')
@validated_operation
def client_portal(client_id):
    client = scoped(db.session, Client, org(), client_id)
    link = None
    if request.method == 'POST':
        days = integer(request.form.get('days', '7'), 1, 30)
        token = new_token()
        grant = PortalGrant(organization_id=org(), client_id=client.id, token_hash=digest(token),
            expires_at=utcnow() + timedelta(days=days), created_by=current_user.id)
        db.session.add(grant)
        db.session.flush()
        audit(db.session, org(), current_user.id, 'portal.issued', 'portal_grant', grant.id,
              'Enlace privado de consulta emitido.', {'client_id': client.id, 'days': days})
        db.session.commit()
        base = current_app.config.get('PUBLIC_BASE_URL', '').rstrip('/') or request.url_root.rstrip('/')
        link = base + url_for('portal.entry') + '#' + token
    grants = PortalGrant.query.filter_by(organization_id=org(), client_id=client.id).order_by(PortalGrant.id.desc()).limit(30).all()
    return render_template('operations/portal_manage.html', client=client, grants=grants, link=link)


@ops_bp.post('/portal/<int:grant_id>/revoke')
@permission_required('portal.manage')
@validated_operation
def revoke_portal(grant_id):
    grant = scoped(db.session, PortalGrant, org(), grant_id, lock=True)
    grant.revoked_at = utcnow()
    audit(db.session, org(), current_user.id, 'portal.revoked', 'portal_grant', grant.id, 'Acceso privado revocado.')
    db.session.commit()
    return redirect(url_for('ops.client_portal', client_id=grant.client_id))


@ops_bp.route('/controls', methods=['GET', 'POST'])
@permission_required('team.manage')
@validated_operation
def controls():
    row = db.session.get(OrganizationControls, org())
    if request.method == 'POST':
        if row is None:
            row = OrganizationControls(organization_id=org())
            db.session.add(row)
        row.require_cash_shift = request.form.get('require_cash_shift') == '1'
        row.collectors_restricted = request.form.get('collectors_restricted') == '1'
        row.updated_at = utcnow()
        audit(db.session, org(), current_user.id, 'controls.updated', 'organization', org(),
              'Controles operativos actualizados.', {'cash': row.require_cash_shift, 'collectors': row.collectors_restricted})
        db.session.commit()
        return redirect(url_for('ops.controls'))
    return render_template('operations/controls.html', control=row)


@ops_bp.get('/readiness')
@permission_required('team.manage')
def readiness():
    from ..readiness import inspect_readiness
    return render_template('operations/readiness.html', checks=inspect_readiness(current_app, org_id=org()))
