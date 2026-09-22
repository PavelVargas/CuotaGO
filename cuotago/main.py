import calendar as pycalendar
import json
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import quote
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .extensions import db
from .models import (
    Asset, Client, CollectionNote, Contract, ContractScheduleChange, Expense, Installment, Payment,
    PaymentPromise, Purchase, PushNotificationLog, Supplier, TenantAuditLog, User,
)
from .module_catalog import module_catalog

main_bp = Blueprint("main", __name__)
CENT = Decimal("0.01")


ASSET_IMAGE_MAX_BYTES = 4 * 1024 * 1024


def read_asset_image_upload(file_storage):
    """Read and validate one product photo without trusting its filename/MIME."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None, None

    payload = file_storage.read(ASSET_IMAGE_MAX_BYTES + 1)
    if not payload:
        raise ValueError("La foto esta vacia.")
    if len(payload) > ASSET_IMAGE_MAX_BYTES:
        raise ValueError("La foto no puede pesar mas de 4 MB.")

    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif payload.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("Usa una foto JPG, PNG o WebP.")
    return payload, mime


def local_today():
    """Current business day using the app timezone, not the server timezone."""
    try:
        timezone_name = current_app.config.get("APP_TIMEZONE", "America/Santo_Domingo")
        return datetime.now(ZoneInfo(timezone_name)).date()
    except Exception:
        return date.today()


def money_decimal(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def parse_money(value, default=None):
    raw = (value or "").strip().replace(",", "")
    if not raw:
        return default
    try:
        return Decimal(raw).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return default


def parse_int(value, default=None, minimum=None):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if minimum is not None and parsed < minimum:
        return default
    return parsed


def parse_date(value):
    try:
        return date.fromisoformat((value or "").strip())
    except (TypeError, ValueError):
        return None


def add_months(day, months=1):
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    final_day = min(day.day, pycalendar.monthrange(year, month)[1])
    return date(year, month, final_day)


def advance_due(day, frequency):
    if frequency == "weekly":
        return day + timedelta(days=7)
    if frequency == "biweekly":
        return day + timedelta(days=14)
    return add_months(day, 1)


def generate_installments(contract, installment_count=None):
    """Generate the payment schedule.

    When the user chooses a number of installments we split the financed amount
    into exactly that many payments, down to the cent. Older callers that only
    provide an installment amount keep the legacy behavior.
    """
    remaining = money_decimal(contract.total_amount) - money_decimal(contract.down_payment)
    due = contract.first_due_date

    if remaining <= Decimal("0.009"):
        return

    if installment_count:
        count = int(installment_count)
        if count < 1 or count > 500:
            raise ValueError("Selecciona entre 1 y 500 cuotas.")

        total_cents = int((remaining * 100).to_integral_value(rounding=ROUND_HALF_UP))
        if count > total_cents:
            raise ValueError("Hay demasiadas cuotas para ese monto.")

        base_cents, extra_cents = divmod(total_cents, count)
        for sequence in range(1, count + 1):
            cents = base_cents + (1 if sequence <= extra_cents else 0)
            amount = Decimal(cents) / Decimal("100")
            contract.installments.append(
                Installment(sequence=sequence, due_date=due, amount=amount, paid_amount=Decimal("0.00"))
            )
            due = advance_due(due, contract.frequency)
        return

    installment_value = money_decimal(contract.installment_amount)
    sequence = 1
    while remaining > Decimal("0.009"):
        if sequence > 500:
            raise ValueError("El plan generaría demasiadas cuotas.")
        amount = min(installment_value, remaining)
        contract.installments.append(
            Installment(sequence=sequence, due_date=due, amount=amount, paid_amount=Decimal("0.00"))
        )
        remaining -= amount
        sequence += 1
        due = advance_due(due, contract.frequency)


def sync_contract_late_fees(contract, today_value=None, commit=False):
    """Persist daily mora without retroactively charging a later activation.

    Agreements created with mora keep the original behavior: each installment
    starts accruing after its due date. If mora is added later, the effective
    start is ``late_fee_started_on`` so old overdue days are never backcharged.
    Once principal is fully paid, mora stops growing on that date.
    """
    rate = money_decimal(getattr(contract, "daily_late_interest", 0))
    if rate <= 0 or contract.status != "active":
        return False
    today_value = today_value or local_today()
    activation_day = getattr(contract, "late_fee_started_on", None) or contract.start_date
    changed = False
    for installment in contract.installments:
        if installment.due_date >= today_value or installment.is_paid:
            continue
        end_day = today_value
        principal_paid_at = installment.principal_paid_at or (installment.paid_at if installment.principal_is_paid else None)
        if principal_paid_at:
            end_day = min(today_value, principal_paid_at.date())
        charge_start = max(installment.due_date, activation_day)
        days_late = max((end_day - charge_start).days, 0)
        base_fee = money_decimal(getattr(installment, "late_fee_base_amount", 0))
        target = money_decimal(base_fee + (rate * days_late))
        current = money_decimal(installment.late_fee_amount)
        if target > current:
            installment.late_fee_amount = target
            changed = True
    if changed and commit:
        db.session.commit()
    return changed


def sync_org_late_fees(commit=True):
    contracts = Contract.query.filter_by(organization_id=current_user.organization_id, status="active").all()
    changed = False
    today_value = local_today()
    for contract in contracts:
        changed = sync_contract_late_fees(contract, today_value=today_value, commit=False) or changed
    if changed and commit:
        db.session.commit()
    return changed


def refresh_asset_status(asset):
    """Keep the legacy status field useful while stock is quantity based."""
    if asset.status == "maintenance" and asset.committed_quantity == 0:
        return
    if asset.available_quantity > 0:
        asset.status = "available"
        return
    if any(c.status == "active" for c in asset.contracts):
        asset.status = "on_loan"
        return
    if any(c.status == "completed" and c.deal_type == "credit_sale" for c in asset.contracts):
        asset.status = "sold"
    else:
        asset.status = "available"


def scoped_client(client_id):
    return Client.query.filter_by(id=client_id, organization_id=current_user.organization_id).first_or_404()


def scoped_asset(asset_id):
    return Asset.query.filter_by(id=asset_id, organization_id=current_user.organization_id).first_or_404()


def scoped_contract(contract_id):
    contract = Contract.query.filter_by(id=contract_id, organization_id=current_user.organization_id).first_or_404()
    sync_contract_late_fees(contract, commit=True)
    return contract


def scoped_payment(payment_id):
    return (
        Payment.query.join(Contract)
        .filter(Payment.id == payment_id, Contract.organization_id == current_user.organization_id)
        .first_or_404()
    )


def scoped_promise(promise_id):
    return PaymentPromise.query.filter_by(
        id=promise_id, organization_id=current_user.organization_id
    ).first_or_404()


def tenant_audit(action, entity_type, entity_id, summary, detail=None):
    db.session.add(TenantAuditLog(
        organization_id=current_user.organization_id,
        actor_user_id=getattr(current_user, "id", None),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=(summary or "")[:240],
        detail=detail,
    ))


def sync_payment_promises(commit=True):
    today_value = local_today()
    promises = PaymentPromise.query.filter_by(
        organization_id=current_user.organization_id, status="pending"
    ).filter(PaymentPromise.promised_date < today_value).all()
    for promise in promises:
        promise.status = "broken"
    if promises and commit:
        db.session.commit()
    return len(promises)


def payment_method_label(value):
    return {
        "cash": "Efectivo",
        "transfer": "Transferencia",
        "deposit": "Depósito",
        "card": "Tarjeta",
        "other": "Otro",
    }.get(value, (value or "Otro").capitalize())


def expense_category_label(value):
    return {
        "fuel": "Combustible",
        "rent": "Alquiler",
        "payroll": "Nómina",
        "repair": "Reparación",
        "transport": "Transporte",
        "services": "Servicios",
        "supplies": "Insumos",
        "other": "Otro",
    }.get(value, (value or "Otro").capitalize())


def client_risk_summary(client):
    today_value = local_today()
    overdue_days = 0
    overdue_count = 0
    for contract in client.contracts:
        if contract.status != "active":
            continue
        for installment in contract.installments:
            if installment.remaining > Decimal("0.009") and installment.due_date < today_value:
                overdue_count += 1
                overdue_days = max(overdue_days, (today_value - installment.due_date).days)
    broken_promises = sum(1 for promise in client.payment_promises if promise.status == "broken")
    if overdue_days >= 15 or broken_promises >= 2:
        return {"level": "high", "label": "Alto riesgo", "reason": f"{overdue_count} cuota(s) vencida(s) · {broken_promises} promesa(s) incumplida(s)"}
    if overdue_count or broken_promises:
        return {"level": "watch", "label": "Atención", "reason": f"{overdue_count} cuota(s) vencida(s) · {broken_promises} promesa(s) incumplida(s)"}
    if client.contracts:
        return {"level": "good", "label": "Buen pagador", "reason": "Sin atrasos ni promesas incumplidas"}
    return {"level": "new", "label": "Sin historial", "reason": "Aún no tiene acuerdos registrados"}


def tenant_installments(active_only=True):
    sync_org_late_fees(commit=True)
    query = Installment.query.join(Contract).filter(Contract.organization_id == current_user.organization_id)
    if active_only:
        query = query.filter(Contract.status == "active")
    return query.order_by(Installment.due_date.asc(), Installment.sequence.asc()).all()


def format_money(value):
    amount = money_decimal(value)
    currency = getattr(getattr(current_user, "organization", None), "currency", None) or current_app.config.get("APP_CURRENCY", "DOP")
    prefix = {"DOP": "RD$", "USD": "US$", "EUR": "€"}.get(currency, currency + " ")
    return f"{prefix}{amount:,.2f}"


def payment_notification_items(limit=100):
    """Build current payment alerts from live installments.

    These alerts do not depend on Web Push, so they also work during a local
    HTTP demo. An alert disappears automatically once its installment is paid.
    """
    today_value = local_today()
    max_day = today_value + timedelta(days=7)
    items = []
    for installment in tenant_installments(active_only=True):
        if installment.remaining <= Decimal("0.009") or installment.due_date > max_day:
            continue

        if installment.due_date < today_value:
            alert_type = "overdue"
            title = "Pago atrasado"
            days_late = (today_value - installment.due_date).days
            detail = f"Venció hace {days_late} día{'s' if days_late != 1 else ''}"
            urgent = True
            priority = 0
        elif installment.due_date == today_value:
            alert_type = "today"
            title = "Pago para hoy"
            detail = "Vence hoy"
            urgent = True
            priority = 1
        else:
            alert_type = "upcoming"
            title = "Próximo pago"
            days_until = (installment.due_date - today_value).days
            detail = "Vence mañana" if days_until == 1 else f"Vence en {days_until} días"
            urgent = False
            priority = 2

        contract = installment.contract
        items.append({
            "id": f"{alert_type}:{installment.id}",
            "type": alert_type,
            "title": title,
            "detail": detail,
            "client": contract.client.full_name,
            "asset": contract.asset.name,
            "contractCode": contract.code or "",
            "amount": format_money(installment.remaining),
            "dueDate": installment.due_date.isoformat(),
            "dueLabel": installment.due_date.strftime("%d/%m/%Y"),
            "urgent": urgent,
            "priority": priority,
            "url": url_for("main.contract_detail", contract_id=contract.id, _anchor="pay"),
            "installmentId": installment.id,
            "contractId": contract.id,
        })

    items.sort(key=lambda item: (item["priority"], item["dueDate"], item["client"].lower()))
    return items[:limit]


def urgent_payment_alert_count():
    try:
        return (
            Installment.query.join(Contract)
            .filter(
                Contract.organization_id == current_user.organization_id,
                Contract.status == "active",
                Installment.due_date <= local_today(),
                or_(
                    Installment.paid_amount < Installment.amount,
                    Installment.late_fee_paid < Installment.late_fee_amount,
                ),
            )
            .count()
        )
    except Exception:
        db.session.rollback()
        return 0


def asset_kind_label(value):
    return {
        "car": "Vehículo",
        "phone": "Celular",
        "motorcycle": "Motor",
        "appliance": "Electrodoméstico",
        "computer": "Computadora",
        "other": "Otro",
    }.get(value, "Otro")


def asset_status_label(value):
    return {
        "available": "Disponible",
        "on_loan": "Entregado",
        "maintenance": "Mantenimiento",
        "sold": "Vendido",
    }.get(value, value or "—")


def contract_status_label(value):
    return {"active": "Activo", "completed": "Completado", "cancelled": "Cancelado"}.get(value, value or "—")


def frequency_label(value):
    return {"weekly": "Semanal", "biweekly": "Quincenal", "monthly": "Mensual"}.get(value, value or "—")


def deal_type_label(value):
    return {"credit_sale": "Venta a crédito", "rental": "Préstamo / alquiler"}.get(value, value or "—")


def whatsapp_text_link(client, message):
    digits = re.sub(r"\D", "", client.phone or "")
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) < 10:
        return ""
    return f"https://wa.me/{digits}?text={quote(message)}"


def whatsapp_link(client, contract=None, installment=None):
    message = f"Hola {client.full_name}, te escribimos para recordarte tu pago"
    if contract:
        message += f" del acuerdo {contract.code or ''}"
    if installment:
        message += f" por {format_money(installment.remaining)}, con fecha {installment.due_date.strftime('%d/%m/%Y')}"
    message += ". Gracias."
    return whatsapp_text_link(client, message)


def statement_whatsapp_link(client):
    active = [contract for contract in client.contracts if contract.status == "active"]
    balance = sum((contract.balance for contract in active), Decimal("0.00"))
    next_items = [contract.next_installment for contract in active if contract.next_installment]
    next_item = min(next_items, key=lambda item: item.due_date) if next_items else None
    message = f"Hola {client.full_name}. Estado de cuenta CuotaGo: saldo pendiente {format_money(balance)}."
    if next_item:
        message += f" Próximo pago {format_money(next_item.remaining)} el {next_item.due_date.strftime('%d/%m/%Y')}."
    message += " Si necesitas el detalle completo, contáctanos. Gracias."
    return whatsapp_text_link(client, message)


def receipt_whatsapp_link(payment):
    contract = payment.contract
    message = (
        f"Hola {contract.client.full_name}. Recibimos {format_money(payment.amount)} "
        f"para el acuerdo {contract.code}. Recibo {payment.receipt_code or f'CGP-{contract.organization_id}-{payment.id:06d}'}. "
        f"Saldo pendiente {format_money(contract.balance)}. Gracias."
    )
    return whatsapp_text_link(contract.client, message)


@main_bp.app_context_processor
def inject_helpers():
    return {
        "money": format_money,
        "asset_kind_label": asset_kind_label,
        "asset_status_label": asset_status_label,
        "contract_status_label": contract_status_label,
        "frequency_label": frequency_label,
        "deal_type_label": deal_type_label,
        "payment_method_label": payment_method_label,
        "expense_category_label": expense_category_label,
        "wa_link": whatsapp_link,
        "statement_wa_link": statement_whatsapp_link,
        "receipt_wa_link": receipt_whatsapp_link,
        "today": local_today(),
        "app_name": current_app.config.get("APP_NAME", "CuotaGo"),
        "notification_count": urgent_payment_alert_count() if current_user.is_authenticated else 0,
    }


@main_bp.get("/")
@login_required
def dashboard():
    if getattr(current_user, "role", "") == "superadmin":
        return redirect(url_for("admin.dashboard"))
    org_id = current_user.organization_id
    today_value = local_today()
    installments = tenant_installments(active_only=True)
    open_installments = [i for i in installments if i.remaining > Decimal("0.009")]
    overdue = [i for i in open_installments if i.due_date < today_value]
    due_today = [i for i in open_installments if i.due_date == today_value]
    upcoming = [i for i in open_installments if today_value < i.due_date <= today_value + timedelta(days=7)]

    active_contracts = Contract.query.filter_by(organization_id=org_id, status="active").all()
    receivable = sum((c.balance for c in active_contracts), Decimal("0.00"))
    overdue_total = sum((i.remaining for i in overdue), Decimal("0.00"))

    overdue_count = len(overdue)
    due_today_count = len(due_today)
    notification_count = overdue_count + due_today_count
    sync_payment_promises(commit=True)
    agenda_promises = PaymentPromise.query.filter_by(organization_id=org_id).filter(
        PaymentPromise.status.in_(["pending", "broken"]),
        PaymentPromise.promised_date <= today_value + timedelta(days=7),
    ).count()
    modules = module_catalog()
    module_status = {
        "agreements": {
            "kind": "small",
            "text": f"Crear y gestionar · {len(active_contracts)} activo{'s' if len(active_contracts) != 1 else ''}",
        },
        "collections": (
            {"kind": "badge-danger", "text": f"{overdue_count} vencido{'s' if overdue_count != 1 else ''}"}
            if overdue_count
            else {"kind": "badge-warning", "text": f"{due_today_count} hoy"}
            if due_today_count
            else {"kind": "small", "text": "Todo al día"}
        ),
        "notifications": (
            {"kind": "badge-danger", "text": f"{notification_count} pendiente{'s' if notification_count != 1 else ''}"}
            if notification_count
            else {"kind": "small", "text": "Todo al día"}
        ),
    }

    return render_template(
        "dashboard.html",
        modules=modules,
        module_status=module_status,
        overdue_count=overdue_count,
        due_today_count=due_today_count,
        reminder_count=len(overdue) + len(due_today) + len(upcoming) + agenda_promises,
        active_count=len(active_contracts),
        receivable=receivable,
        overdue_total=overdue_total,
    )


@main_bp.get("/documents")
@login_required
def documents():
    modules = module_catalog()
    return render_template(
        "documents/index.html",
        modules=modules,
        module_count=len(modules),
        generated_on=local_today(),
    )


@main_bp.get("/reminders")
@login_required
def reminders():
    sync_payment_promises(commit=True)
    items = payment_notification_items(limit=500)
    overdue = [item for item in items if item["type"] == "overdue"]
    due_today = [item for item in items if item["type"] == "today"]
    upcoming = [item for item in items if item["type"] == "upcoming"]
    today_value = local_today()
    promises = PaymentPromise.query.filter_by(organization_id=current_user.organization_id).filter(
        PaymentPromise.status.in_(["pending", "broken"]),
        PaymentPromise.promised_date <= today_value + timedelta(days=7),
    ).order_by(PaymentPromise.promised_date.asc()).all()
    broken_promises = [p for p in promises if p.status == "broken"]
    today_promises = [p for p in promises if p.status == "pending" and p.promised_date == today_value]
    upcoming_promises = [p for p in promises if p.status == "pending" and p.promised_date > today_value]
    return render_template(
        "reminders/index.html",
        items=items, overdue=overdue, due_today=due_today, upcoming=upcoming,
        broken_promises=broken_promises, today_promises=today_promises, upcoming_promises=upcoming_promises,
        reminder_count=len(items) + len(promises),
    )


@main_bp.get("/notifications")
@login_required
def notifications():
    items = payment_notification_items(limit=100)
    overdue = [item for item in items if item["type"] == "overdue"]
    due_today = [item for item in items if item["type"] == "today"]
    upcoming = [item for item in items if item["type"] == "upcoming"]
    return render_template(
        "notifications/index.html",
        items=items,
        overdue=overdue,
        due_today=due_today,
        upcoming=upcoming,
        urgent_count=len(overdue) + len(due_today),
    )


@main_bp.get("/api/notifications")
@login_required
def notifications_api():
    items = payment_notification_items(limit=30)
    urgent_count = sum(1 for item in items if item["urgent"])
    return jsonify({
        "ok": True,
        "count": len(items),
        "urgentCount": urgent_count,
        "items": items,
    })


@main_bp.route("/clients", methods=["GET"])
@login_required
def clients():
    q = request.args.get("q", "").strip()
    query = Client.query.filter_by(organization_id=current_user.organization_id)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                Client.full_name.ilike(pattern),
                Client.phone.ilike(pattern),
                Client.document_id.ilike(pattern),
            )
        )
    items = query.order_by(Client.full_name.asc()).all()
    return render_template("clients/list.html", clients=items, q=q)


@main_bp.route("/clients/new", methods=["GET", "POST"])
@login_required
def client_new():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        if len(full_name) < 2:
            flash("Escribe el nombre del cliente.", "error")
            return render_template("clients/form.html", client=None)

        client = Client(
            organization_id=current_user.organization_id,
            full_name=full_name,
            phone=request.form.get("phone", "").strip(),
            email=request.form.get("email", "").strip(),
            document_id=request.form.get("document_id", "").strip(),
            address=request.form.get("address", "").strip(),
            notes=request.form.get("notes", "").strip(),
        )
        db.session.add(client)
        db.session.flush()
        tenant_audit("client.created", "client", client.id, f"Cliente {client.full_name} creado.")
        db.session.commit()
        flash("Cliente creado.", "success")
        return redirect(url_for("main.clients"))

    return render_template("clients/form.html", client=None)


@main_bp.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
@login_required
def client_edit(client_id):
    client = scoped_client(client_id)
    if request.method == "POST":
        before = {"full_name": client.full_name, "phone": client.phone, "email": client.email, "document_id": client.document_id, "address": client.address}
        full_name = request.form.get("full_name", "").strip()
        if len(full_name) < 2:
            flash("Escribe el nombre del cliente.", "error")
            return render_template("clients/form.html", client=client)
        client.full_name = full_name
        client.phone = request.form.get("phone", "").strip()
        client.email = request.form.get("email", "").strip()
        client.document_id = request.form.get("document_id", "").strip()
        client.address = request.form.get("address", "").strip()
        client.notes = request.form.get("notes", "").strip()
        tenant_audit(
            "client.updated", "client", client.id, f"Cliente {client.full_name} actualizado.",
            json.dumps({"before": before, "after": {"full_name": client.full_name, "phone": client.phone, "email": client.email, "document_id": client.document_id, "address": client.address}}, ensure_ascii=False),
        )
        db.session.commit()
        flash("Cliente actualizado.", "success")
        return redirect(url_for("main.clients"))
    return render_template("clients/form.html", client=client)


@main_bp.get("/clients/<int:client_id>")
@login_required
def client_detail(client_id):
    client = scoped_client(client_id)
    sync_payment_promises(commit=True)
    changed = False
    for contract in client.contracts:
        changed = sync_contract_late_fees(contract, commit=False) or changed
    if changed:
        db.session.commit()

    contracts = sorted(client.contracts, key=lambda item: item.created_at or datetime.min, reverse=True)
    payments = sorted(
        [payment for contract in contracts for payment in contract.payments],
        key=lambda item: item.paid_at or datetime.min,
        reverse=True,
    )
    active = [contract for contract in contracts if contract.status == "active"]
    balance = sum((contract.balance for contract in active), Decimal("0.00"))
    paid = sum((contract.paid_total for contract in contracts), Decimal("0.00"))
    today_value = local_today()
    overdue = [
        installment for contract in active for installment in contract.installments
        if installment.remaining > Decimal("0.009") and installment.due_date < today_value
    ]
    promises = PaymentPromise.query.filter_by(
        organization_id=current_user.organization_id, client_id=client.id
    ).order_by(PaymentPromise.promised_date.desc(), PaymentPromise.created_at.desc()).all()
    notes = CollectionNote.query.filter_by(
        organization_id=current_user.organization_id, client_id=client.id
    ).order_by(CollectionNote.created_at.desc()).all()
    actor_ids = {
        actor_id
        for actor_id in (
            [item.created_by_user_id for item in notes]
            + [item.created_by_user_id for item in promises]
            + [item.created_by_user_id for item in payments]
            + [change.created_by_user_id for contract in contracts for change in contract.schedule_changes]
        )
        if actor_id
    }
    actors = {user.id: user.name for user in User.query.filter(User.id.in_(actor_ids)).all()} if actor_ids else {}

    timeline = []
    for contract in contracts:
        timeline.append({
            "kind": "agreement", "title": f"Acuerdo {contract.code}", "detail": contract.asset.name,
            "amount": money_decimal(contract.total_amount), "date": contract.created_at,
            "url": url_for("main.contract_detail", contract_id=contract.id),
        })
        for payment in contract.payments:
            timeline.append({
                "kind": "payment", "title": "Abono" if payment.payment_kind == "advance" else "Pago",
                "detail": f"{contract.code} · {payment_method_label(payment.method)}",
                "amount": money_decimal(payment.amount), "date": payment.paid_at,
                "url": url_for("main.payment_receipt", payment_id=payment.id),
            })
        for change in contract.schedule_changes:
            timeline.append({
                "kind": "schedule", "title": "Cuotas reprogramadas",
                "detail": f"{contract.code} · {change.new_open_count} cuota(s) · {change.reason or 'Sin nota'}",
                "amount": None, "date": change.created_at,
                "url": url_for("main.contract_detail", contract_id=contract.id),
            })
    for promise in promises:
        timeline.append({
            "kind": "promise", "title": "Promesa de pago",
            "detail": f"{promise.promised_date.strftime('%d/%m/%Y')} · {promise.status}",
            "amount": money_decimal(promise.amount), "date": promise.created_at, "url": None,
        })
    for note in notes:
        timeline.append({
            "kind": "note", "title": "Nota de cobranza", "detail": note.body,
            "amount": None, "date": note.created_at, "url": None,
        })
    timeline.sort(key=lambda item: item["date"] or datetime.min, reverse=True)

    return render_template(
        "clients/detail.html", client=client, contracts=contracts, payments=payments, promises=promises,
        notes=notes, timeline=timeline[:40], actors=actors, risk=client_risk_summary(client), balance=balance, paid=paid,
        overdue_count=len(overdue), active_count=len(active),
    )


@main_bp.post("/clients/<int:client_id>/notes")
@login_required
def client_note_add(client_id):
    client = scoped_client(client_id)
    body = (request.form.get("body") or "").strip()
    if len(body) < 2:
        flash("Escribe una nota de cobranza.", "error")
        return redirect(url_for("main.client_detail", client_id=client.id, _anchor="notes"))
    contract_id = parse_int(request.form.get("contract_id"))
    contract = None
    if contract_id:
        contract = Contract.query.filter_by(
            id=contract_id, organization_id=current_user.organization_id, client_id=client.id
        ).first()
        if contract is None:
            abort(400)
    note = CollectionNote(
        organization_id=current_user.organization_id, client_id=client.id,
        contract_id=contract.id if contract else None, body=body[:2000],
        created_by_user_id=current_user.id,
    )
    db.session.add(note)
    db.session.flush()
    tenant_audit("client.note_added", "client", client.id, f"Nota de cobranza agregada a {client.full_name}.", body[:500])
    db.session.commit()
    flash("Nota guardada.", "success")
    return redirect(url_for("main.client_detail", client_id=client.id, _anchor="notes"))


@main_bp.post("/clients/<int:client_id>/promises")
@login_required
def client_promise_add(client_id):
    client = scoped_client(client_id)
    promised_date = parse_date(request.form.get("promised_date"))
    amount = parse_money(request.form.get("amount"))
    contract_id = parse_int(request.form.get("contract_id"))
    if promised_date is None or amount is None or amount <= 0:
        flash("Indica fecha y monto válidos para la promesa.", "error")
        return redirect(url_for("main.client_detail", client_id=client.id, _anchor="promises"))
    contract = None
    if contract_id:
        contract = Contract.query.filter_by(
            id=contract_id, organization_id=current_user.organization_id, client_id=client.id
        ).first()
        if contract is None:
            abort(400)
    promise = PaymentPromise(
        organization_id=current_user.organization_id, client_id=client.id,
        contract_id=contract.id if contract else None, promised_date=promised_date, amount=amount,
        note=(request.form.get("note") or "").strip()[:240], created_by_user_id=current_user.id,
    )
    db.session.add(promise)
    db.session.flush()
    tenant_audit(
        "promise.created", "payment_promise", promise.id,
        f"Promesa de {format_money(amount)} para {client.full_name} el {promised_date.strftime('%d/%m/%Y')}.",
    )
    db.session.commit()
    flash("Promesa de pago registrada.", "success")
    return redirect(url_for("main.client_detail", client_id=client.id, _anchor="promises"))


@main_bp.post("/promises/<int:promise_id>/status")
@login_required
def promise_status(promise_id):
    promise = scoped_promise(promise_id)
    status = (request.form.get("status") or "").strip()
    if status not in {"pending", "fulfilled", "broken"}:
        abort(400)
    promise.status = status
    if status == "fulfilled":
        promise.fulfilled_at = datetime.utcnow()
    elif status != "fulfilled":
        promise.fulfilled_at = None
        promise.fulfilled_payment_id = None
    tenant_audit(
        "promise.status_changed", "payment_promise", promise.id,
        f"Promesa de {promise.client.full_name} marcada como {status}.",
    )
    db.session.commit()
    flash("Promesa actualizada.", "success")
    return redirect(url_for("main.client_detail", client_id=promise.client_id, _anchor="promises"))


@main_bp.get("/clients/<int:client_id>/statement")
@login_required
def client_statement(client_id):
    client = scoped_client(client_id)
    sync_payment_promises(commit=True)
    for contract in client.contracts:
        sync_contract_late_fees(contract, commit=False)
    db.session.commit()
    contracts = sorted(client.contracts, key=lambda item: item.created_at or datetime.min, reverse=True)
    active = [item for item in contracts if item.status == "active"]
    payments = sorted([p for c in contracts for p in c.payments], key=lambda p: p.paid_at, reverse=True)
    totals = {
        "agreed": sum((money_decimal(c.total_amount) for c in contracts), Decimal("0.00")),
        "paid": sum((c.paid_total for c in contracts), Decimal("0.00")),
        "balance": sum((c.balance for c in active), Decimal("0.00")),
        "late_fee": sum((c.late_fee_balance for c in active), Decimal("0.00")),
    }
    next_items = [c.next_installment for c in active if c.next_installment]
    next_item = min(next_items, key=lambda item: item.due_date) if next_items else None
    return render_template(
        "clients/statement.html", client=client, contracts=contracts, payments=payments[:20],
        totals=totals, next_item=next_item, risk=client_risk_summary(client),
    )


@main_bp.get("/assets/<int:asset_id>/image")
@login_required
def asset_image(asset_id):
    asset = scoped_asset(asset_id)
    if not asset.image_mime or not asset.image_data:
        abort(404)
    response = Response(bytes(asset.image_data), mimetype=asset.image_mime)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@main_bp.get("/assets")
@login_required
def assets():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    query = Asset.query.filter_by(organization_id=current_user.organization_id)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                Asset.name.ilike(pattern),
                Asset.brand.ilike(pattern),
                Asset.model.ilike(pattern),
                Asset.identifier.ilike(pattern),
                Asset.serial_number.ilike(pattern),
            )
        )
    items = query.order_by(Asset.created_at.desc()).all()
    changed = False
    for item in items:
        before = item.status
        refresh_asset_status(item)
        changed = changed or before != item.status
    if changed:
        db.session.commit()
    if status:
        items = [item for item in items if item.status == status]
    return render_template("assets/list.html", assets=items, q=q, status=status)


@main_bp.route("/assets/new", methods=["GET", "POST"])
@login_required
def asset_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        value = parse_money(request.form.get("estimated_value"), Decimal("0.00"))
        sale_price = parse_money(request.form.get("sale_price"), Decimal("0.00"))
        quantity_total = parse_int(request.form.get("quantity_total"), 1, minimum=1) or 1
        kind = request.form.get("kind", "other")
        if len(name) < 2:
            flash("Escribe un nombre para el bien.", "error")
            return render_template("assets/form.html", asset=None)
        if kind not in {"car", "phone", "motorcycle", "appliance", "computer", "other"}:
            kind = "other"

        try:
            image_data, image_mime = read_asset_image_upload(request.files.get("image"))
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("assets/form.html", asset=None)

        asset = Asset(
            organization_id=current_user.organization_id,
            kind=kind,
            name=name,
            brand=request.form.get("brand", "").strip(),
            model=request.form.get("model", "").strip(),
            identifier=request.form.get("identifier", "").strip(),
            serial_number=request.form.get("serial_number", "").strip(),
            estimated_value=value or Decimal("0.00"),
            sale_price=sale_price or Decimal("0.00"),
            quantity_total=quantity_total,
            status="available",
            notes=request.form.get("notes", "").strip(),
            image_data=image_data,
            image_mime=image_mime,
        )
        db.session.add(asset)
        db.session.commit()
        flash("Bien registrado.", "success")
        return redirect(url_for("main.assets"))
    return render_template("assets/form.html", asset=None)


@main_bp.route("/assets/<int:asset_id>/edit", methods=["GET", "POST"])
@login_required
def asset_edit(asset_id):
    asset = scoped_asset(asset_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if len(name) < 2:
            flash("Escribe un nombre para el bien.", "error")
            return render_template("assets/form.html", asset=asset)
        asset.name = name
        requested_kind = request.form.get("kind", "other")
        asset.kind = requested_kind if requested_kind in {"car", "phone", "motorcycle", "appliance", "computer", "other"} else "other"
        asset.brand = request.form.get("brand", "").strip()
        asset.model = request.form.get("model", "").strip()
        asset.identifier = request.form.get("identifier", "").strip()
        asset.serial_number = request.form.get("serial_number", "").strip()
        asset.estimated_value = parse_money(request.form.get("estimated_value"), Decimal("0.00"))
        asset.sale_price = parse_money(request.form.get("sale_price"), Decimal("0.00"))
        requested_quantity = parse_int(request.form.get("quantity_total"), int(asset.quantity_total or 1), minimum=1)
        if requested_quantity is None or requested_quantity < asset.committed_quantity:
            flash(f"No puedes bajar la existencia por debajo de {asset.committed_quantity}; esa cantidad ya está entregada o vendida.", "error")
            return render_template("assets/form.html", asset=asset)
        asset.quantity_total = requested_quantity
        asset.notes = request.form.get("notes", "").strip()

        if request.form.get("remove_image") == "1":
            asset.image_data = None
            asset.image_mime = None
        image_upload = request.files.get("image")
        if image_upload and image_upload.filename:
            try:
                image_data, image_mime = read_asset_image_upload(image_upload)
            except ValueError as exc:
                flash(str(exc), "error")
                return render_template("assets/form.html", asset=asset)
            asset.image_data = image_data
            asset.image_mime = image_mime

        requested_status = request.form.get("status", "available")
        if requested_status == "maintenance" and asset.committed_quantity == 0:
            asset.status = "maintenance"
        else:
            if asset.status == "maintenance":
                asset.status = "available"
            refresh_asset_status(asset)
        db.session.commit()
        flash("Bien actualizado.", "success")
        return redirect(url_for("main.assets"))
    return render_template("assets/form.html", asset=asset)


@main_bp.get("/purchases")
@login_required
def purchases():
    items = (
        Purchase.query.filter_by(organization_id=current_user.organization_id)
        .order_by(Purchase.purchase_date.desc(), Purchase.created_at.desc(), Purchase.id.desc())
        .all()
    )
    invested = sum((money_decimal(item.total_cost) for item in items), Decimal("0.00"))
    units = sum((int(item.quantity or 0) for item in items), 0)

    # Purchases are shown as orders instead of isolated lines. New multi-item
    # purchases share a batch_key; old records remain visible as one-line orders.
    grouped = {}
    for item in items:
        group_key = item.batch_key or f"legacy-{item.id}"
        order = grouped.setdefault(group_key, {
            "id": item.id,
            "code": f"OC-{item.id:05d}",
            "purchase_date": item.purchase_date,
            "reference": item.reference or "",
            "supplier": item.supplier_record.name if item.supplier_record else (item.supplier or "Proveedor no registrado"),
            "supplier_id": item.supplier_id,
            "created_at": item.created_at,
            "lines": [],
            "units": 0,
            "total": Decimal("0.00"),
        })
        order["lines"].append(item)
        order["units"] += int(item.quantity or 0)
        order["total"] += money_decimal(item.total_cost)
        if item.id < order["id"]:
            order["id"] = item.id
            order["code"] = f"OC-{item.id:05d}"

    orders = list(grouped.values())
    orders.sort(key=lambda order: (order["purchase_date"], order["created_at"] or datetime.min), reverse=True)
    supplier_ids = {item.supplier_id for item in items if item.supplier_id}
    legacy_suppliers = {
        (item.supplier or "").strip().casefold()
        for item in items
        if not item.supplier_id and (item.supplier or "").strip()
    }

    return render_template(
        "purchases/list.html",
        orders=orders,
        invested=money_decimal(invested),
        units=units,
        order_count=len(orders),
        supplier_count=len(supplier_ids) + len(legacy_suppliers),
    )


@main_bp.route("/purchases/new", methods=["GET", "POST"])
@login_required
def purchase_new():
    assets_list = (
        Asset.query.filter_by(organization_id=current_user.organization_id)
        .order_by(Asset.name.asc())
        .all()
    )
    suppliers_list = (
        Supplier.query.filter_by(organization_id=current_user.organization_id)
        .order_by(Supplier.name.asc())
        .all()
    )

    def submitted_rows():
        fields = {
            "mode": request.form.getlist("item_mode"),
            "asset_id": request.form.getlist("item_asset_id"),
            "asset_name": request.form.getlist("item_name"),
            "asset_kind": request.form.getlist("item_kind"),
            "quantity": request.form.getlist("item_quantity"),
            "unit_cost": request.form.getlist("item_unit_cost"),
            "notes": request.form.getlist("item_notes"),
        }
        row_count = max((len(values) for values in fields.values()), default=0)

        # Compatibility with old one-item forms/clients. Sale price is
        # deliberately ignored: a purchase must never change the selling price.
        if row_count == 0:
            legacy_has_values = any(
                request.form.get(name)
                for name in ("asset_id", "asset_name", "quantity", "unit_cost")
            )
            if legacy_has_values:
                return [{
                    "mode": "existing" if request.form.get("asset_id") else "new",
                    "asset_id": request.form.get("asset_id", ""),
                    "asset_name": request.form.get("asset_name", ""),
                    "asset_kind": request.form.get("asset_kind", "other"),
                    "quantity": request.form.get("quantity", "1"),
                    "unit_cost": request.form.get("unit_cost", ""),
                    "notes": request.form.get("notes", ""),
                }]
            return []

        rows = []
        for index in range(row_count):
            def value(key, default=""):
                values = fields[key]
                return values[index] if index < len(values) else default

            asset_value = value("asset_id")
            mode = value("mode", "new" if asset_value == "__new__" else "existing")
            if asset_value == "__new__":
                mode = "new"
                asset_value = ""
            rows.append({
                "mode": mode,
                "asset_id": asset_value,
                "asset_name": value("asset_name"),
                "asset_kind": value("asset_kind", "other"),
                "quantity": value("quantity", "1"),
                "unit_cost": value("unit_cost"),
                "notes": value("notes"),
            })
        return rows

    if request.method == "POST":
        rows = submitted_rows()
        supplier_choice = request.form.get("supplier_id", "").strip()
        new_supplier_name = request.form.get("new_supplier_name", "").strip()
        new_supplier_phone = request.form.get("new_supplier_phone", "").strip()
        legacy_supplier_name = request.form.get("supplier", "").strip()
        if not supplier_choice and legacy_supplier_name:
            supplier_choice = "__new__"
            new_supplier_name = legacy_supplier_name
        reference = request.form.get("reference", "").strip()
        purchase_date = parse_date(request.form.get("purchase_date")) or local_today()
        errors = []
        prepared = []
        allowed_kinds = {"car", "phone", "motorcycle", "appliance", "computer", "other"}

        supplier_record = None
        create_supplier = False
        if supplier_choice == "__new__":
            if len(new_supplier_name) < 2:
                errors.append("Escribe el nombre del proveedor nuevo.")
            else:
                supplier_record = next(
                    (item for item in suppliers_list if item.name.strip().casefold() == new_supplier_name.casefold()),
                    None,
                )
                create_supplier = supplier_record is None
        else:
            supplier_id = parse_int(supplier_choice, None, minimum=1)
            if supplier_id:
                supplier_record = Supplier.query.filter_by(
                    id=supplier_id,
                    organization_id=current_user.organization_id,
                ).first()
            if supplier_record is None:
                errors.append("Selecciona un proveedor o crea uno nuevo.")

        if not rows:
            errors.append("Agrega al menos un artículo a la compra.")

        for index, row in enumerate(rows, start=1):
            mode = (row.get("mode") or "existing").strip()
            asset = None
            asset_id = parse_int(row.get("asset_id"), None, minimum=1)
            asset_name = (row.get("asset_name") or "").strip()
            asset_kind = (row.get("asset_kind") or "other").strip()
            quantity = parse_int(row.get("quantity"), None, minimum=1)
            unit_cost = parse_money(row.get("unit_cost"))
            notes = (row.get("notes") or "").strip()
            prefix = f"Artículo {index}: "

            if mode == "existing":
                if asset_id:
                    asset = Asset.query.filter_by(
                        id=asset_id, organization_id=current_user.organization_id
                    ).first()
                if asset is None:
                    errors.append(prefix + "selecciona un producto válido del inventario.")
            else:
                mode = "new"
                if len(asset_name) < 2:
                    errors.append(prefix + "escribe el nombre del producto.")
                if asset_kind not in allowed_kinds:
                    asset_kind = "other"

            if quantity is None or quantity < 1:
                errors.append(prefix + "la cantidad debe ser al menos 1.")
            if unit_cost is None or unit_cost <= 0:
                errors.append(prefix + "el costo por unidad debe ser mayor que cero.")

            prepared.append({
                "mode": mode,
                "asset": asset,
                "asset_name": asset_name,
                "asset_kind": asset_kind,
                "quantity": quantity,
                "unit_cost": unit_cost,
                "notes": notes,
            })

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "purchases/form.html",
                assets=assets_list,
                suppliers=suppliers_list,
                form=request.form,
                rows=rows or [{"mode": "existing" if assets_list else "new", "quantity": "1", "asset_kind": "other"}],
                default_date=local_today().isoformat(),
            )

        if create_supplier:
            supplier_record = Supplier(
                organization_id=current_user.organization_id,
                name=new_supplier_name,
                phone=new_supplier_phone or None,
            )
            db.session.add(supplier_record)
            db.session.flush()

        batch_key = str(uuid.uuid4())
        total_units = 0
        created_purchases = 0
        for item in prepared:
            quantity = item["quantity"]
            unit_cost = item["unit_cost"]
            asset = item["asset"]

            if item["mode"] == "new":
                asset = Asset(
                    organization_id=current_user.organization_id,
                    kind=item["asset_kind"],
                    name=item["asset_name"],
                    estimated_value=unit_cost,
                    sale_price=0,
                    quantity_total=quantity,
                    status="available",
                )
                db.session.add(asset)
                db.session.flush()
            else:
                previous_quantity = max(int(asset.quantity_total or 0), 0)
                previous_cost = money_decimal(asset.estimated_value)
                new_quantity = previous_quantity + quantity
                if previous_quantity > 0 and previous_cost > 0:
                    weighted_cost = (
                        previous_cost * Decimal(previous_quantity)
                        + unit_cost * Decimal(quantity)
                    ) / Decimal(new_quantity)
                    asset.estimated_value = money_decimal(weighted_cost)
                else:
                    asset.estimated_value = unit_cost
                # Important: purchases update cost/stock only. The selling price
                # is managed from inventory and is never changed here.
                asset.quantity_total = new_quantity
                if asset.status != "maintenance":
                    refresh_asset_status(asset)

            db.session.add(Purchase(
                organization_id=current_user.organization_id,
                asset=asset,
                supplier_id=supplier_record.id,
                batch_key=batch_key,
                supplier=supplier_record.name,
                reference=reference,
                purchase_date=purchase_date,
                quantity=quantity,
                unit_cost=unit_cost,
                unit_sale_price=0,
                notes=item["notes"],
            ))
            total_units += quantity
            created_purchases += 1

        db.session.commit()
        flash(
            f"Orden de compra registrada: {created_purchases} artículo(s) · {total_units} unidad(es).",
            "success",
        )
        return redirect(url_for("main.purchases"))

    default_mode = "existing" if assets_list else "new"
    return render_template(
        "purchases/form.html",
        assets=assets_list,
        suppliers=suppliers_list,
        form={},
        rows=[{"mode": default_mode, "quantity": "1", "asset_kind": "other"}],
        default_date=local_today().isoformat(),
    )


@main_bp.get("/contracts")
@login_required
def contracts():
    sync_org_late_fees(commit=True)
    status = request.args.get("status", "").strip()
    query = Contract.query.filter_by(organization_id=current_user.organization_id)
    if status:
        query = query.filter_by(status=status)
    items = query.order_by(Contract.created_at.desc()).all()
    return render_template("contracts/list.html", contracts=items, status=status)


@main_bp.route("/contracts/new", methods=["GET", "POST"])
@login_required
def contract_new():
    """Create an agreement in one mobile-first screen.

    A client and/or asset can be created inline, so the user never has to leave
    this flow just to prepare master data first. Existing client/asset IDs are
    still accepted for backwards compatibility and faster repeat business.
    """
    clients_list = Client.query.filter_by(organization_id=current_user.organization_id).order_by(Client.full_name.asc()).all()
    all_assets = Asset.query.filter_by(organization_id=current_user.organization_id).order_by(Asset.name.asc()).all()
    for item in all_assets:
        refresh_asset_status(item)
    assets_list = [item for item in all_assets if item.status != "maintenance" and item.available_quantity > 0]

    today_value = local_today()
    default_start = today_value.isoformat()
    default_due = add_months(today_value, 1).isoformat()

    if request.method == "POST":
        client_id = request.form.get("client_id", type=int)
        asset_id = request.form.get("asset_id", type=int)
        client = None
        asset = None

        if client_id:
            client = Client.query.filter_by(
                id=client_id,
                organization_id=current_user.organization_id,
            ).first()
        if asset_id:
            asset = Asset.query.filter_by(
                id=asset_id,
                organization_id=current_user.organization_id,
            ).first()

        client_name = request.form.get("client_name", "").strip()
        client_phone = request.form.get("client_phone", "").strip()
        asset_name = request.form.get("asset_name", "").strip()
        asset_kind = request.form.get("asset_kind", "other").strip()
        asset_identifier = request.form.get("asset_identifier", "").strip()
        quantity = parse_int(request.form.get("quantity"), 1, minimum=1) or 1
        asset_stock_quantity = parse_int(request.form.get("asset_stock_quantity"), 1, minimum=1) or 1

        deal_type = request.form.get("deal_type", "credit_sale")
        down = parse_money(request.form.get("down_payment"), Decimal("0.00"))
        unit_price = parse_money(request.form.get("unit_price"))
        if unit_price is None and asset is not None and money_decimal(asset.estimated_value) > 0:
            unit_price = money_decimal(asset.estimated_value)
        profit_margin_percent = parse_money(request.form.get("profit_margin_percent"), Decimal("0.00"))
        installment_count = parse_int(request.form.get("installment_count"), None, minimum=1)

        # The product price is the base. The seller chooses a margin for this
        # specific agreement, then CuotaGo distributes the financed total into
        # the selected number of installments. Keep the hidden total as a
        # compatibility fallback for older forms/tests.
        total = parse_money(request.form.get("total_amount"))
        base_amount = total
        if unit_price is not None:
            base_amount = money_decimal(unit_price * quantity)
            margin_rate = (profit_margin_percent or Decimal("0.00")) / Decimal("100")
            total = money_decimal(base_amount * (Decimal("1.00") + margin_rate))

        installment = parse_money(request.form.get("installment_amount"))
        financed = None
        if total is not None and down is not None:
            financed = money_decimal(total - down)
        if installment_count and financed is not None and financed > Decimal("0.009"):
            installment = money_decimal(financed / Decimal(installment_count))
        elif installment_count and financed is not None:
            installment = Decimal("0.00")

        daily_late_interest = parse_money(request.form.get("daily_late_interest"), Decimal("0.00"))
        frequency = request.form.get("frequency", "monthly")
        start = parse_date(request.form.get("start_date")) or today_value
        if frequency not in {"weekly", "biweekly", "monthly"}:
            frequency = "monthly"
        first_due = parse_date(request.form.get("first_due_date")) or advance_due(start, frequency)

        errors = []
        if not client and len(client_name) < 2:
            errors.append("Escribe el nombre del cliente o selecciona uno guardado.")
        if not asset and len(asset_name) < 2:
            errors.append("Escribe el bien que entregas o selecciona uno guardado.")
        if deal_type not in {"credit_sale", "rental"}:
            errors.append("Selecciona un tipo de acuerdo válido.")
        if asset_kind not in {"car", "phone", "motorcycle", "appliance", "computer", "other"}:
            asset_kind = "other"
        if unit_price is not None and unit_price <= 0:
            errors.append("El precio por unidad debe ser mayor que cero.")
        if profit_margin_percent is None or profit_margin_percent < 0:
            errors.append("El margen de ganancia no puede ser negativo.")
        elif profit_margin_percent > Decimal("1000.00"):
            errors.append("El margen de ganancia no puede superar 1000%.")
        if total is None or total <= 0:
            errors.append("El precio del acuerdo debe ser mayor que cero.")
        if down is None or down < 0:
            errors.append("El inicial no puede ser negativo.")
        if total is not None and down is not None and down > total:
            errors.append("El inicial no puede ser mayor al total.")
        if installment_count is not None and installment_count > 500:
            errors.append("Selecciona 500 cuotas o menos.")
        if installment_count is None and (installment is None or installment <= 0):
            errors.append("Selecciona cuántas cuotas tendrá el acuerdo.")
        if installment_count is not None and financed is not None and financed > Decimal("0.009"):
            financed_cents = int((financed * 100).to_integral_value(rounding=ROUND_HALF_UP))
            if installment_count > financed_cents:
                errors.append("Hay demasiadas cuotas para ese monto.")
        if daily_late_interest is None or daily_late_interest < 0:
            errors.append("El interés diario no puede ser negativo.")
        if quantity < 1:
            errors.append("La cantidad a entregar debe ser al menos 1.")
        if asset is not None:
            refresh_asset_status(asset)
            if asset.status == "maintenance":
                errors.append("Ese bien está en mantenimiento.")
            elif quantity > asset.available_quantity:
                errors.append(f"Solo quedan {asset.available_quantity} unidad(es) disponibles de {asset.name}.")
        elif quantity > asset_stock_quantity:
            errors.append("La cantidad a entregar no puede superar la existencia del bien nuevo.")
        if first_due < start:
            errors.append("El primer pago no puede ser antes de la entrega.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "contracts/form.html",
                clients=clients_list,
                assets=assets_list,
                form=request.form,
                default_start=default_start,
                default_due=default_due,
            )

        # Inline creation makes the common mobile flow a single screen.
        if client is None:
            client = Client(
                organization_id=current_user.organization_id,
                full_name=client_name,
                phone=client_phone,
            )
            db.session.add(client)

        if asset is None:
            asset = Asset(
                organization_id=current_user.organization_id,
                kind=asset_kind,
                name=asset_name,
                identifier=asset_identifier,
                estimated_value=(money_decimal(unit_price) if unit_price is not None else (money_decimal(total / quantity) if total and quantity else Decimal("0.00"))),
                sale_price=(money_decimal(total / quantity) if total and quantity else Decimal("0.00")),
                quantity_total=asset_stock_quantity,
                status="available",
            )
            db.session.add(asset)

        db.session.flush()
        contract = Contract(
            organization_id=current_user.organization_id,
            client=client,
            asset=asset,
            deal_type=deal_type,
            total_amount=total,
            base_amount=money_decimal(base_amount if base_amount is not None else total),
            profit_margin_percent=profit_margin_percent or Decimal("0.00"),
            down_payment=down,
            installment_amount=installment,
            quantity=quantity,
            daily_late_interest=daily_late_interest or Decimal("0.00"),
            late_fee_started_on=(start if (daily_late_interest or Decimal("0.00")) > 0 else None),
            frequency=frequency,
            start_date=start,
            first_due_date=first_due,
            status="active",
            notes=request.form.get("notes", "").strip(),
        )
        db.session.add(contract)
        db.session.flush()
        contract.code = f"CG-{start.year}-{contract.id:05d}"
        try:
            generate_installments(contract, installment_count=installment_count)
            if installment_count and contract.installments:
                contract.installment_amount = contract.installments[0].amount
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return render_template(
                "contracts/form.html",
                clients=clients_list,
                assets=assets_list,
                form=request.form,
                default_start=default_start,
                default_due=default_due,
            )

        if total - down <= Decimal("0.009"):
            contract.status = "completed"
        refresh_asset_status(asset)
        tenant_audit(
            "contract.created", "contract", contract.id,
            f"Acuerdo {contract.code} creado para {client.full_name} por {format_money(total)}.",
        )
        db.session.commit()
        flash("Listo. Acuerdo creado, ganancia y cuotas calculadas.", "success")
        return redirect(url_for("main.contract_detail", contract_id=contract.id))

    return render_template(
        "contracts/form.html",
        clients=clients_list,
        assets=assets_list,
        form={},
        default_start=default_start,
        default_due=default_due,
    )


@main_bp.get("/contracts/<int:contract_id>")
@login_required
def contract_detail(contract_id):
    contract = scoped_contract(contract_id)
    return render_template("contracts/detail.html", contract=contract)


@main_bp.post("/contracts/<int:contract_id>/late-fee")
@login_required
def contract_enable_late_fee(contract_id):
    """Enable mora from today without charging prior overdue days."""
    contract = scoped_contract(contract_id)
    if contract.status != "active":
        flash("Solo puedes agregar mora a un acuerdo activo.", "error")
        return redirect(url_for("main.contract_detail", contract_id=contract.id))

    if money_decimal(contract.daily_late_interest) > Decimal("0.009"):
        flash("La mora ya está activa en este acuerdo.", "error")
        return redirect(url_for("main.contract_detail", contract_id=contract.id))

    daily_amount = parse_money(request.form.get("daily_late_interest"))
    if daily_amount is None or daily_amount <= 0:
        flash("Escribe un monto de mora diario mayor que cero.", "error")
        return redirect(url_for("main.contract_detail", contract_id=contract.id))

    contract.daily_late_interest = daily_amount
    contract.late_fee_started_on = local_today()
    tenant_audit(
        "contract.late_fee_enabled", "contract", contract.id,
        f"Mora de {format_money(daily_amount)} por día activada en {contract.code}.",
    )
    db.session.commit()
    flash(
        f"Mora de {format_money(daily_amount)} por día activada desde hoy. No se cobraron días anteriores.",
        "success",
    )
    return redirect(url_for("main.contract_detail", contract_id=contract.id))


@main_bp.post("/contracts/<int:contract_id>/reschedule")
@login_required
def contract_reschedule(contract_id):
    contract = scoped_contract(contract_id)
    if contract.status != "active":
        flash("Solo puedes reprogramar un acuerdo activo.", "error")
        return redirect(url_for("main.contract_detail", contract_id=contract.id))

    new_first_due = parse_date(request.form.get("first_due_date"))
    frequency = (request.form.get("frequency") or contract.frequency).strip()
    count = parse_int(request.form.get("installment_count"), minimum=1)
    reason = (request.form.get("reason") or "").strip()[:240]
    if frequency not in {"weekly", "biweekly", "monthly"}:
        frequency = contract.frequency
    if new_first_due is None or new_first_due < local_today():
        flash("La nueva primera fecha debe ser hoy o una fecha futura.", "error")
        return redirect(url_for("main.contract_detail", contract_id=contract.id, _anchor="manage"))
    if count is None or count > 120:
        flash("Selecciona entre 1 y 120 cuotas pendientes.", "error")
        return redirect(url_for("main.contract_detail", contract_id=contract.id, _anchor="manage"))

    open_items = [item for item in contract.installments if not item.is_paid]
    if not open_items:
        flash("Este acuerdo no tiene cuotas pendientes para reprogramar.", "error")
        return redirect(url_for("main.contract_detail", contract_id=contract.id))

    pending_principal = money_decimal(contract.principal_balance)
    pending_late_fee = sum((item.late_fee_remaining for item in open_items), Decimal("0.00"))
    old_next_due = min((item.due_date for item in open_items), default=None)
    snapshot = [
        {
            "sequence": item.sequence,
            "due_date": item.due_date.isoformat(),
            "amount": str(money_decimal(item.amount)),
            "paid_amount": str(money_decimal(item.paid_amount)),
            "late_fee_amount": str(money_decimal(item.late_fee_amount)),
            "late_fee_base_amount": str(money_decimal(getattr(item, "late_fee_base_amount", 0))),
            "late_fee_paid": str(money_decimal(item.late_fee_paid)),
        }
        for item in open_items
    ]

    old_ids = [item.id for item in open_items if item.id is not None]
    if old_ids:
        PushNotificationLog.query.filter(PushNotificationLog.installment_id.in_(old_ids)).delete(synchronize_session=False)
    for item in open_items:
        db.session.delete(item)
    db.session.flush()

    paid_sequences = [item.sequence for item in contract.installments if item.is_paid]
    next_sequence = max(paid_sequences, default=0) + 1
    total_cents = int((pending_principal * 100).to_integral_value(rounding=ROUND_HALF_UP))
    if total_cents > 0 and count > total_cents:
        count = total_cents
    if total_cents <= 0:
        count = 1
    base_cents, extra_cents = divmod(total_cents, count) if count else (0, 0)
    due = new_first_due
    new_items = []
    for offset in range(count):
        cents = base_cents + (1 if offset < extra_cents else 0)
        item = Installment(
            sequence=next_sequence + offset,
            due_date=due,
            amount=Decimal(cents) / Decimal("100"),
            paid_amount=Decimal("0.00"),
            late_fee_amount=(money_decimal(pending_late_fee) if offset == 0 else Decimal("0.00")),
            late_fee_base_amount=(money_decimal(pending_late_fee) if offset == 0 else Decimal("0.00")),
            late_fee_paid=Decimal("0.00"),
        )
        contract.installments.append(item)
        new_items.append(item)
        due = advance_due(due, frequency)

    old_frequency = contract.frequency
    contract.frequency = frequency
    contract.first_due_date = new_first_due
    contract.installment_amount = money_decimal(new_items[0].amount) if new_items else Decimal("0.00")

    change = ContractScheduleChange(
        organization_id=current_user.organization_id, contract=contract, created_by_user_id=current_user.id,
        reason=reason, old_frequency=old_frequency, new_frequency=frequency,
        old_next_due_date=old_next_due, new_next_due_date=new_first_due,
        old_open_count=len(open_items), new_open_count=len(new_items),
        pending_principal=pending_principal, pending_late_fee=money_decimal(pending_late_fee),
        snapshot=json.dumps(snapshot, ensure_ascii=False),
    )
    db.session.add(change)
    db.session.flush()
    tenant_audit(
        "contract.rescheduled", "contract", contract.id,
        f"Acuerdo {contract.code} reprogramado a {len(new_items)} cuota(s).",
        json.dumps({
            "old_next_due": old_next_due.isoformat() if old_next_due else None,
            "new_next_due": new_first_due.isoformat(),
            "old_frequency": old_frequency, "new_frequency": frequency,
            "pending_principal": str(pending_principal), "pending_late_fee": str(pending_late_fee),
            "reason": reason,
        }, ensure_ascii=False),
    )
    db.session.commit()
    flash(f"Cuotas reprogramadas. El saldo quedó distribuido en {len(new_items)} cuota(s).", "success")
    return redirect(url_for("main.contract_detail", contract_id=contract.id))


@main_bp.post("/contracts/<int:contract_id>/delete")
@login_required
def contract_delete(contract_id):
    """Delete one tenant-owned agreement and release its inventory quantity."""
    contract = scoped_contract(contract_id)
    asset = contract.asset
    installment_ids = [item.id for item in contract.installments if item.id is not None]

    try:
        if installment_ids:
            PushNotificationLog.query.filter(
                PushNotificationLog.installment_id.in_(installment_ids)
            ).delete(synchronize_session=False)
        tenant_audit(
            "contract.deleted", "contract", contract.id,
            f"Acuerdo {contract.code} de {contract.client.full_name} eliminado.",
        )
        db.session.delete(contract)
        db.session.flush()
        # Reload the relationship after the delete so stock/status are computed
        # only from agreements that still exist.
        db.session.expire(asset, ["contracts"])
        refresh_asset_status(asset)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("No se pudo eliminar el acuerdo %s", contract_id)
        flash("No se pudo eliminar el acuerdo. Intenta nuevamente.", "error")
        return redirect(url_for("main.contract_detail", contract_id=contract_id))

    flash("Acuerdo eliminado. El producto volvió a quedar disponible para crear otro acuerdo.", "success")
    return redirect(url_for("main.contracts"))


@main_bp.post("/contracts/<int:contract_id>/pay")
@login_required
def contract_pay(contract_id):
    contract = scoped_contract(contract_id)
    if contract.status != "active":
        flash("Ese acuerdo no está activo.", "error")
        return redirect(url_for("main.contract_detail", contract_id=contract.id))

    balance_before = contract.balance
    amount = parse_money(request.form.get("amount"))
    if amount is None or amount <= 0:
        flash("Escribe un monto válido.", "error")
        return redirect(url_for("main.contract_detail", contract_id=contract.id))
    if amount > balance_before + Decimal("0.009"):
        flash("El pago no puede superar el saldo pendiente.", "error")
        return redirect(url_for("main.contract_detail", contract_id=contract.id))

    method = request.form.get("method", "cash")
    if method not in {"cash", "transfer", "deposit", "card", "other"}:
        method = "other"
    reference = (request.form.get("reference") or "").strip()[:120]

    now_value = datetime.utcnow()
    try:
        business_now = datetime.now(ZoneInfo(current_app.config.get("APP_TIMEZONE", "America/Santo_Domingo"))).replace(tzinfo=None)
    except Exception:
        business_now = now_value
    to_allocate = amount
    interest_applied_total = Decimal("0.00")
    for installment in contract.installments:
        if to_allocate <= Decimal("0.009"):
            break
        if installment.remaining <= Decimal("0.009"):
            continue

        fee_due = installment.late_fee_remaining
        if fee_due > Decimal("0.009"):
            applied_fee = min(fee_due, to_allocate)
            installment.late_fee_paid = money_decimal(installment.late_fee_paid) + applied_fee
            interest_applied_total += applied_fee
            to_allocate -= applied_fee

        if to_allocate > Decimal("0.009") and installment.principal_remaining > Decimal("0.009"):
            applied_principal = min(installment.principal_remaining, to_allocate)
            installment.paid_amount = money_decimal(installment.paid_amount) + applied_principal
            to_allocate -= applied_principal
            if installment.principal_is_paid and not installment.principal_paid_at:
                installment.principal_paid_at = business_now

        if installment.remaining <= Decimal("0.009"):
            installment.paid_at = now_value

    payment_kind = request.form.get("payment_kind", "payment")
    if payment_kind not in {"payment", "advance"}:
        payment_kind = "payment"
    payment_note = request.form.get("note", "").strip()
    if payment_kind == "advance" and not payment_note:
        payment_note = "Abono"

    payment = Payment(
        contract=contract,
        amount=amount,
        late_fee_amount=money_decimal(interest_applied_total),
        method=method,
        reference=reference,
        payment_kind=payment_kind,
        created_by_user_id=current_user.id,
        note=payment_note,
        paid_at=now_value,
    )
    db.session.add(payment)
    db.session.flush()
    payment.receipt_code = f"CGP-{current_user.organization_id}-{payment.id:06d}"

    # A payment that covers a due promise closes the oldest applicable promise automatically.
    pending_promises = (
        PaymentPromise.query.filter_by(
            organization_id=current_user.organization_id, contract_id=contract.id, status="pending"
        )
        .filter(PaymentPromise.promised_date <= local_today())
        .order_by(PaymentPromise.promised_date.asc(), PaymentPromise.id.asc())
        .all()
    )
    remaining_for_promises = amount
    for promise in pending_promises:
        if remaining_for_promises + Decimal("0.009") < money_decimal(promise.amount):
            continue
        promise.status = "fulfilled"
        promise.fulfilled_payment_id = payment.id
        promise.fulfilled_at = now_value
        remaining_for_promises -= money_decimal(promise.amount)

    projected_balance = balance_before - amount
    if projected_balance <= Decimal("0.009"):
        contract.status = "completed"
    refresh_asset_status(contract.asset)
    tenant_audit(
        "payment.created", "payment", payment.id,
        f"{('Abono' if payment_kind == 'advance' else 'Pago')} de {format_money(amount)} en {contract.code}.",
        json.dumps({"method": method, "reference": reference, "late_fee": str(interest_applied_total)}, ensure_ascii=False),
    )

    db.session.commit()
    action_label = "Abono" if payment_kind == "advance" else "Pago"
    flash(f"{action_label} de {format_money(amount)} registrado.", "success")
    next_url = request.form.get("next", "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    if request.form.get("show_receipt") == "1":
        return redirect(url_for("main.payment_receipt", payment_id=payment.id))
    return redirect(url_for("main.contract_detail", contract_id=contract.id))


@main_bp.get("/payments/<int:payment_id>/receipt")
@login_required
def payment_receipt(payment_id):
    payment = scoped_payment(payment_id)
    contract = payment.contract
    receipt_code = payment.receipt_code or f"CGP-{contract.organization_id}-{payment.id:06d}"
    registered_by = db.session.get(User, payment.created_by_user_id) if payment.created_by_user_id else None
    return render_template(
        "collections/receipt.html", payment=payment, contract=contract, receipt_code=receipt_code,
        whatsapp_url=receipt_whatsapp_link(payment), registered_by=registered_by,
    )


@main_bp.get("/collections")
@login_required
def collections():
    today_value = local_today()
    installments = tenant_installments(active_only=True)
    open_installments = [i for i in installments if i.remaining > Decimal("0.009")]
    overdue = [i for i in open_installments if i.due_date < today_value]
    due_today = [i for i in open_installments if i.due_date == today_value]
    upcoming = [i for i in open_installments if today_value < i.due_date <= today_value + timedelta(days=30)]
    return render_template(
        "collections/list.html",
        overdue=overdue,
        due_today=due_today,
        upcoming=upcoming,
        overdue_total=sum((i.remaining for i in overdue), Decimal("0.00")),
    )


@main_bp.get("/calendar")
@login_required
def payment_calendar():
    """Interactive payment calendar with client-side, real-time filtering."""
    today_value = local_today()
    items = [i for i in tenant_installments(active_only=True) if i.remaining > Decimal("0.009")]
    future_items = [i for i in items if i.due_date >= today_value]
    next_due = future_items[0].due_date if future_items else None

    calendar_events = []
    seen_clients = {}
    for installment in items:
        contract = installment.contract
        client = contract.client
        seen_clients[client.id] = {
            "id": client.id,
            "name": client.full_name,
        }
        calendar_events.append(
            {
                "id": installment.id,
                "date": installment.due_date.isoformat(),
                "date_label": installment.due_date.strftime("%d/%m/%Y"),
                "client_id": client.id,
                "client_name": client.full_name,
                "client_phone": client.phone or "",
                "client_document": client.document_id or "",
                "contract_id": contract.id,
                "contract_code": contract.code or f"#{contract.id}",
                "contract_url": url_for("main.contract_detail", contract_id=contract.id, _anchor="pay"),
                "asset_name": contract.asset.name,
                "quantity": max(int(contract.quantity or 1), 1),
                "sequence": installment.sequence,
                "amount": format_money(installment.remaining),
                "late_fee": format_money(installment.late_fee_remaining) if installment.late_fee_remaining > Decimal("0.009") else "",
            }
        )

    calendar_clients = sorted(seen_clients.values(), key=lambda item: item["name"].casefold())
    return render_template(
        "calendar/list.html",
        today_value=today_value,
        pending_count=len(items),
        next_due=next_due,
        calendar_events=calendar_events,
        calendar_clients=calendar_clients,
    )


@main_bp.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():
    if request.method == "POST":
        expense_date = parse_date(request.form.get("expense_date")) or local_today()
        amount = parse_money(request.form.get("amount"))
        category = (request.form.get("category") or "other").strip()
        method = (request.form.get("method") or "cash").strip()
        allowed_categories = {"fuel", "rent", "payroll", "repair", "transport", "services", "supplies", "other"}
        if category not in allowed_categories:
            category = "other"
        if method not in {"cash", "transfer", "deposit", "card", "other"}:
            method = "other"
        if amount is None or amount <= 0:
            flash("Escribe un monto de gasto válido.", "error")
            return redirect(url_for("main.expenses"))
        expense = Expense(
            organization_id=current_user.organization_id, expense_date=expense_date, category=category, amount=amount,
            method=method, reference=(request.form.get("reference") or "").strip()[:120],
            note=(request.form.get("note") or "").strip()[:240], created_by_user_id=current_user.id,
        )
        db.session.add(expense)
        db.session.flush()
        tenant_audit(
            "expense.created", "expense", expense.id,
            f"Gasto de {format_money(amount)} · {expense_category_label(category)}.",
            json.dumps({"method": method, "date": expense_date.isoformat(), "reference": expense.reference}, ensure_ascii=False),
        )
        db.session.commit()
        flash("Gasto registrado.", "success")
        return redirect(url_for("main.expenses"))

    period = (request.args.get("period") or "month").strip().lower()
    today_value = local_today()
    if period == "today":
        start = today_value
    elif period == "7d":
        start = today_value - timedelta(days=6)
    elif period == "all":
        start = None
    else:
        period = "month"
        start = today_value.replace(day=1)
    query = Expense.query.filter_by(organization_id=current_user.organization_id)
    if start:
        query = query.filter(Expense.expense_date >= start)
    rows = query.order_by(Expense.expense_date.desc(), Expense.created_at.desc()).all()
    total = sum((money_decimal(item.amount) for item in rows), Decimal("0.00"))
    category_totals = {}
    for item in rows:
        category_totals[item.category] = category_totals.get(item.category, Decimal("0.00")) + money_decimal(item.amount)
    top_categories = sorted(category_totals.items(), key=lambda pair: pair[1], reverse=True)[:5]
    return render_template(
        "expenses/index.html", expenses=rows, total=total, period=period, top_categories=top_categories, today_value=today_value,
    )


@main_bp.post("/expenses/<int:expense_id>/delete")
@login_required
def expense_delete(expense_id):
    expense = Expense.query.filter_by(id=expense_id, organization_id=current_user.organization_id).first_or_404()
    summary = f"Gasto de {format_money(expense.amount)} · {expense_category_label(expense.category)} eliminado."
    tenant_audit("expense.deleted", "expense", expense.id, summary)
    db.session.delete(expense)
    db.session.commit()
    flash("Gasto eliminado.", "success")
    return redirect(url_for("main.expenses"))


@main_bp.get("/audit")
@login_required
def audit_log():
    if getattr(current_user, "role", "") not in {"owner", "admin"}:
        abort(403)
    logs = TenantAuditLog.query.filter_by(organization_id=current_user.organization_id).order_by(
        TenantAuditLog.created_at.desc()
    ).limit(250).all()
    actor_ids = {log.actor_user_id for log in logs if log.actor_user_id}
    actors = {user.id: user.name for user in User.query.filter(User.id.in_(actor_ids)).all()} if actor_ids else {}
    return render_template("settings/audit.html", logs=logs, actors=actors)


@main_bp.get("/reports")
@login_required
def reports():
    """Simple business report focused on collections, portfolio and profit."""
    sync_org_late_fees(commit=True)
    org_id = current_user.organization_id
    today_value = local_today()

    report_period = (request.args.get("period") or "month").strip().lower()
    if report_period not in {"today", "7d", "month", "all"}:
        report_period = "month"
    report_status = (request.args.get("status") or "all").strip().lower()
    if report_status not in {"all", "active", "overdue", "completed"}:
        report_status = "all"
    selected_client_id = parse_int(request.args.get("client_id"))

    period_labels = {
        "today": "Hoy",
        "7d": "7 días",
        "month": "Este mes",
        "all": "Histórico",
    }
    period_label = period_labels[report_period]
    if report_period == "today":
        period_start = today_value
    elif report_period == "7d":
        period_start = today_value - timedelta(days=6)
    elif report_period == "month":
        period_start = today_value.replace(day=1)
    else:
        period_start = None

    report_clients = (
        Client.query.filter_by(organization_id=org_id)
        .order_by(Client.full_name.asc())
        .all()
    )
    if selected_client_id and not any(client.id == selected_client_id for client in report_clients):
        selected_client_id = None

    contracts_all = (
        Contract.query.filter_by(organization_id=org_id)
        .order_by(Contract.created_at.desc())
        .all()
    )
    if selected_client_id:
        contracts_all = [contract for contract in contracts_all if contract.client_id == selected_client_id]

    def contract_is_overdue(contract):
        return contract.status == "active" and any(
            item.remaining > Decimal("0.009") and item.due_date < today_value
            for item in contract.installments
        )

    if report_status == "active":
        contracts_scope = [contract for contract in contracts_all if contract.status == "active"]
    elif report_status == "completed":
        contracts_scope = [contract for contract in contracts_all if contract.status == "completed"]
    elif report_status == "overdue":
        contracts_scope = [contract for contract in contracts_all if contract_is_overdue(contract)]
    else:
        contracts_scope = list(contracts_all)

    active = [contract for contract in contracts_scope if contract.status == "active"]
    completed = [contract for contract in contracts_scope if contract.status == "completed"]
    active_installments = [item for contract in active for item in contract.installments]
    all_installments = [item for contract in contracts_scope for item in contract.installments]
    all_payments = [payment for contract in contracts_scope for payment in contract.payments]

    receivable = sum((contract.balance for contract in active), Decimal("0.00"))
    overdue_installments = [
        item for item in active_installments
        if item.remaining > Decimal("0.009") and item.due_date < today_value
    ]
    overdue_total = sum((item.remaining for item in overdue_installments), Decimal("0.00"))
    overdue_client_ids = {item.contract.client_id for item in overdue_installments}
    active_client_ids = {contract.client_id for contract in active}
    current_client_ids = active_client_ids - overdue_client_ids
    upcoming_items = [
        item for item in active_installments
        if item.remaining > Decimal("0.009") and today_value <= item.due_date <= today_value + timedelta(days=7)
    ]
    upcoming_total = sum((item.remaining for item in upcoming_items), Decimal("0.00"))

    def date_in_period(value):
        if value is None:
            return False
        value_date = value.date() if isinstance(value, datetime) else value
        return period_start is None or period_start <= value_date <= today_value

    period_payments = [payment for payment in all_payments if date_in_period(payment.paid_at)]
    period_down_payments = [
        contract for contract in contracts_scope
        if money_decimal(contract.down_payment) > 0 and date_in_period(contract.created_at)
    ]
    period_collected = (
        sum((money_decimal(payment.amount) for payment in period_payments), Decimal("0.00"))
        + sum((money_decimal(contract.down_payment) for contract in period_down_payments), Decimal("0.00"))
    )
    period_payment_count = len(period_payments) + len(period_down_payments)
    payment_method_totals = {key: Decimal("0.00") for key in ("cash", "transfer", "deposit", "card", "other")}
    for payment in period_payments:
        key = payment.method if payment.method in payment_method_totals else "other"
        payment_method_totals[key] += money_decimal(payment.amount)
    down_payment_total = sum((money_decimal(contract.down_payment) for contract in period_down_payments), Decimal("0.00"))

    expense_rows = Expense.query.filter_by(organization_id=org_id).all()
    period_expenses = [item for item in expense_rows if date_in_period(item.expense_date)]
    expenses_period_total = sum((money_decimal(item.amount) for item in period_expenses), Decimal("0.00"))
    cash_flow_net = period_collected - expenses_period_total

    financed_total = sum((money_decimal(contract.total_amount) for contract in contracts_scope), Decimal("0.00"))
    profit_contracts = [
        contract for contract in contracts_scope
        if money_decimal(contract.base_amount) > 0 and money_decimal(contract.total_amount) > 0
    ]
    profit_untracked_count = len(contracts_scope) - len(profit_contracts)
    capital_total = sum((money_decimal(contract.base_amount) for contract in profit_contracts), Decimal("0.00"))
    profit_expected = sum((contract.profit_amount for contract in profit_contracts), Decimal("0.00"))
    capital_recovered = Decimal("0.00")
    profit_realized = Decimal("0.00")
    for contract in profit_contracts:
        total = money_decimal(contract.total_amount)
        received_principal = min(money_decimal(contract.principal_paid_total), total)
        ratio = (received_principal / total) if total > 0 else Decimal("0")
        capital_recovered += money_decimal(contract.base_amount) * ratio
        profit_realized += money_decimal(contract.profit_amount) * ratio
    capital_recovered = money_decimal(capital_recovered)
    profit_realized = money_decimal(profit_realized)
    capital_pending = max(capital_total - capital_recovered, Decimal("0.00"))
    profit_pending = max(profit_expected - profit_realized, Decimal("0.00"))
    profit_margin_percent = (profit_expected / capital_total * Decimal("100")) if capital_total > 0 else Decimal("0.00")
    profit_margin_percent = money_decimal(profit_margin_percent)

    late_fee_generated = sum((money_decimal(item.late_fee_amount) for item in all_installments), Decimal("0.00"))
    late_fee_pending = sum((item.late_fee_remaining for item in all_installments), Decimal("0.00"))
    late_fee_collected = sum((money_decimal(payment.late_fee_amount) for payment in all_payments), Decimal("0.00"))

    assets = Asset.query.filter_by(organization_id=org_id).all()
    inventory_available_units = sum((asset.available_quantity for asset in assets), 0)
    inventory_committed_units = sum((asset.committed_quantity for asset in assets), 0)
    inventory_available_value = sum(
        (money_decimal(asset.estimated_value) * Decimal(asset.available_quantity) for asset in assets),
        Decimal("0.00"),
    )
    inventory_sale_value = sum(
        (
            (money_decimal(asset.sale_price) if money_decimal(asset.sale_price) > 0 else money_decimal(asset.estimated_value))
            * Decimal(asset.available_quantity)
            for asset in assets
        ),
        Decimal("0.00"),
    )
    inventory_potential_profit = inventory_sale_value - inventory_available_value

    purchases_scope = Purchase.query.filter_by(organization_id=org_id).all()
    period_purchases = [item for item in purchases_scope if date_in_period(item.purchase_date)]
    purchases_period_invested = sum((money_decimal(item.total_cost) for item in period_purchases), Decimal("0.00"))
    purchases_period_expected_profit = sum((money_decimal(item.expected_profit) for item in period_purchases), Decimal("0.00"))

    chart_start = period_start or (today_value - timedelta(days=29))
    if (today_value - chart_start).days > 30:
        chart_start = today_value - timedelta(days=29)
    chart_days = [chart_start + timedelta(days=offset) for offset in range((today_value - chart_start).days + 1)]
    if not chart_days:
        chart_days = [today_value]
    daily_collected = {day: Decimal("0.00") for day in chart_days}
    for payment in all_payments:
        payment_day = payment.paid_at.date()
        if payment_day in daily_collected:
            daily_collected[payment_day] += money_decimal(payment.amount)
    for contract in contracts_scope:
        created_day = contract.created_at.date() if contract.created_at else None
        if created_day in daily_collected and money_decimal(contract.down_payment) > 0:
            daily_collected[created_day] += money_decimal(contract.down_payment)

    chart_values = [money_decimal(daily_collected[day]) for day in chart_days]
    chart_total = sum(chart_values, Decimal("0.00"))
    chart_max_value = max(chart_values, default=Decimal("0.00"))
    chart_has_data = chart_max_value > Decimal("0.009")
    chart_ceiling = chart_max_value if chart_has_data else Decimal("1.00")
    points = []
    for index, value in enumerate(chart_values):
        if len(chart_values) == 1:
            x = Decimal("500")
        else:
            x = Decimal("20") + (Decimal(index) * Decimal("960") / Decimal(len(chart_values) - 1))
        y = Decimal("155") - (value / chart_ceiling * Decimal("118"))
        points.append((float(x), float(y)))
    chart_points_svg = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    if points:
        chart_area_svg = f"20,155 {chart_points_svg} 980,155"
    else:
        chart_area_svg = "20,155 980,155"
    chart_first_label = chart_days[0].strftime("%d/%m")
    chart_last_label = chart_days[-1].strftime("%d/%m")
    chart_title = {
        "today": "Cobros de hoy",
        "7d": "Cobros de los últimos 7 días",
        "month": "Cobros de este mes",
        "all": "Cobros de los últimos 30 días",
    }[report_period]

    recent_activity = []
    for contract in contracts_scope:
        if contract.created_at:
            recent_activity.append({
                "kind": "agreement",
                "label": "Acuerdo",
                "client": contract.client.full_name,
                "detail": contract.asset.name,
                "date": contract.created_at.strftime("%d/%m/%Y"),
                "timestamp": contract.created_at,
                "amount": money_decimal(contract.total_amount),
                "url": url_for("main.contract_detail", contract_id=contract.id),
            })
        for payment in contract.payments:
            payment_label = "Abono" if payment.payment_kind == "advance" else "Pago"
            recent_activity.append({
                "kind": "payment",
                "label": payment_label,
                "client": contract.client.full_name,
                "detail": contract.asset.name,
                "date": payment.paid_at.strftime("%d/%m/%Y"),
                "timestamp": payment.paid_at,
                "amount": money_decimal(payment.amount),
                "url": url_for("main.contract_detail", contract_id=contract.id, _anchor="pay"),
            })
    if not selected_client_id:
        for expense in period_expenses:
            recent_activity.append({
                "kind": "expense",
                "label": "Gasto",
                "client": expense_category_label(expense.category),
                "detail": expense.note or payment_method_label(expense.method),
                "date": expense.expense_date.strftime("%d/%m/%Y"),
                "timestamp": expense.created_at or datetime.combine(expense.expense_date, datetime.min.time()),
                "amount": money_decimal(expense.amount),
                "url": url_for("main.expenses"),
            })
    recent_activity.sort(key=lambda item: item["timestamp"], reverse=True)
    recent_activity = recent_activity[:8]

    return render_template(
        "reports/index.html",
        report_period=report_period,
        period_label=period_label,
        report_status=report_status,
        selected_client_id=selected_client_id,
        report_clients=report_clients,
        active_count=len(active),
        completed_count=len(completed),
        receivable=receivable,
        overdue_total=overdue_total,
        overdue_clients_count=len(overdue_client_ids),
        current_clients_count=len(current_client_ids),
        upcoming_total=upcoming_total,
        period_collected=period_collected,
        period_payment_count=period_payment_count,
        payment_method_totals=payment_method_totals,
        down_payment_total=down_payment_total,
        expenses_period_total=expenses_period_total,
        cash_flow_net=cash_flow_net,
        financed_total=financed_total,
        capital_total=capital_total,
        capital_recovered=capital_recovered,
        capital_pending=capital_pending,
        profit_expected=profit_expected,
        profit_realized=profit_realized,
        profit_pending=profit_pending,
        profit_margin_percent=profit_margin_percent,
        profit_untracked_count=profit_untracked_count,
        late_fee_generated=late_fee_generated,
        late_fee_collected=late_fee_collected,
        late_fee_pending=late_fee_pending,
        inventory_available_units=inventory_available_units,
        inventory_committed_units=inventory_committed_units,
        inventory_available_value=inventory_available_value,
        inventory_sale_value=inventory_sale_value,
        inventory_potential_profit=inventory_potential_profit,
        purchases_period_invested=purchases_period_invested,
        purchases_period_expected_profit=purchases_period_expected_profit,
        chart_title=chart_title,
        chart_total=chart_total,
        chart_max_value=chart_max_value,
        chart_has_data=chart_has_data,
        chart_points_svg=chart_points_svg,
        chart_area_svg=chart_area_svg,
        chart_first_label=chart_first_label,
        chart_last_label=chart_last_label,
        recent_activity=recent_activity,
    )


@main_bp.get("/subscription-status")
@login_required
def subscription_status():
    subscription = getattr(current_user.organization, "subscription", None)
    effective_status = subscription.effective_status if subscription else "pending"
    labels = {
        "pending": "Sin configurar",
        "trial": "Prueba",
        "active": "Activa",
        "past_due": "Pago pendiente",
        "expired": "Vencida",
        "suspended": "Suspendida",
        "cancelled": "Cancelada",
    }
    return render_template(
        "subscription_status.html",
        subscription=subscription,
        effective_status=effective_status,
        status_label=labels.get(effective_status, effective_status.title()),
    )


@main_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        business_name = request.form.get("business_name", "").strip()
        user_name = request.form.get("name", "").strip()
        currency = request.form.get("currency", "DOP").strip().upper()
        if len(business_name) < 2 or len(user_name) < 2:
            flash("Nombre del negocio y usuario son obligatorios.", "error")
        else:
            current_user.organization.name = business_name
            current_user.name = user_name
            current_user.organization.currency = currency if currency in {"DOP", "USD", "EUR"} else "DOP"
            db.session.commit()
            flash("Configuración guardada.", "success")
            return redirect(url_for("main.settings"))
    return render_template("settings/index.html")
