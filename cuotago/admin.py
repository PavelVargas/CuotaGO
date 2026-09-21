import calendar
import csv
import io
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from .extensions import db
from .models import (
    AdminAuditLog,
    Asset,
    Client,
    Contract,
    Organization,
    OrganizationSubscription,
    Payment,
    PushNotificationLog,
    PushSubscription,
    SubscriptionPayment,
    SubscriptionPlan,
    User,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/superadmin")

SUBSCRIPTION_STATUSES = ("pending", "trial", "active", "past_due", "suspended", "cancelled")
STATUS_LABELS = {
    "pending": "Sin configurar",
    "trial": "Prueba",
    "active": "Activa",
    "past_due": "Pago pendiente",
    "expired": "Vencida",
    "suspended": "Suspendida",
    "cancelled": "Cancelada",
}
STATUS_TONES = {
    "pending": "neutral",
    "trial": "info",
    "active": "success",
    "past_due": "warning",
    "expired": "danger",
    "suspended": "danger",
    "cancelled": "muted",
}


def superadmin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if getattr(current_user, "role", "") != "superadmin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _organization_or_404(organization_id):
    organization = db.session.get(Organization, organization_id)
    if organization is None:
        abort(404)
    if organization.id == current_user.organization_id:
        abort(400, description="La organizacion del superadmin no puede modificarse desde este panel.")
    return organization


def _subscription_or_create(organization):
    if organization.subscription is None:
        organization.subscription = OrganizationSubscription(status="pending")
        db.session.add(organization.subscription)
        db.session.flush()
    return organization.subscription


def _owner_for(organization):
    owner = next((user for user in organization.users if user.role == "owner"), None)
    if owner is not None:
        return owner
    return min(organization.users, key=lambda user: user.created_at) if organization.users else None


def _parse_date(value, *, field_name="Fecha"):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} no es valida.") from exc


def _parse_decimal(value, *, field_name="Monto", allow_empty=True):
    raw = (value or "").strip().replace(",", "")
    if not raw and allow_empty:
        return None
    try:
        amount = Decimal(raw or "0").quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} no es valido.") from exc
    if amount < 0:
        raise ValueError(f"{field_name} no puede ser negativo.")
    return amount


def _add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _period_end(start, months):
    return _add_months(start, max(1, months)) - timedelta(days=1)


def _plan_or_none(raw_plan_id, *, active_only=False):
    raw = (raw_plan_id or "").strip()
    if not raw:
        return None
    try:
        plan_id = int(raw)
    except ValueError as exc:
        raise ValueError("Plan no valido.") from exc
    plan = db.session.get(SubscriptionPlan, plan_id)
    if plan is None or (active_only and not plan.is_active):
        raise ValueError("Plan no valido.")
    return plan


def _slugify(value):
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    code = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return code or "plan"


def _unique_plan_code(name, ignore_id=None):
    base = _slugify(name)[:40]
    candidate = base
    number = 2
    while True:
        query = SubscriptionPlan.query.filter_by(code=candidate)
        if ignore_id is not None:
            query = query.filter(SubscriptionPlan.id != ignore_id)
        if query.first() is None:
            return candidate
        suffix = f"-{number}"
        candidate = f"{base[:40-len(suffix)]}{suffix}"
        number += 1


def _audit(action, summary, *, organization_id=None, target_type="organization", target_id=None, detail=None):
    db.session.add(
        AdminAuditLog(
            actor_user_id=getattr(current_user, "id", None),
            organization_id=organization_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            summary=summary[:240],
            detail=detail,
        )
    )


def _normalize_confirmation(value):
    return " ".join((value or "").strip().split()).casefold()


def _confirmation_phrase(organization, action):
    prefixes = {
        "clear": "LIMPIAR",
        "reset": "VACIAR",
        "delete": "ELIMINAR",
    }
    prefix = prefixes.get(action)
    if prefix is None:
        raise ValueError("Accion de confirmacion no valida.")
    return f"{prefix} {organization.name}"


def _require_company_confirmation(organization, action):
    expected = _confirmation_phrase(organization, action)
    confirmation = request.form.get("confirm_phrase") or ""
    if _normalize_confirmation(confirmation) != _normalize_confirmation(expected):
        flash(f'Frase incorrecta. Escribe "{expected}" para continuar.', "error")
        return False
    return True


def _count_by_org(model, *, extra_filter=None):
    query = db.session.query(model.organization_id, func.count(model.id)).group_by(model.organization_id)
    if extra_filter is not None:
        query = query.filter(extra_filter)
    return {org_id: count for org_id, count in query.all()}


def _rows_for_organizations(organizations):
    user_counts = _count_by_org(User)
    client_counts = _count_by_org(Client)
    asset_counts = _count_by_org(Asset)
    contract_counts = _count_by_org(Contract)
    push_counts = _count_by_org(PushSubscription, extra_filter=PushSubscription.is_active.is_(True))

    rows = []
    for organization in organizations:
        subscription = organization.subscription
        effective_status = subscription.effective_status if subscription else "pending"
        rows.append(
            {
                "organization": organization,
                "owner": _owner_for(organization),
                "subscription": subscription,
                "status": effective_status,
                "status_label": STATUS_LABELS.get(effective_status, effective_status.title()),
                "status_tone": STATUS_TONES.get(effective_status, "neutral"),
                "plan": subscription.plan if subscription else None,
                "amount": subscription.effective_amount if subscription else Decimal("0.00"),
                "days_remaining": subscription.days_remaining if subscription else None,
                "users": user_counts.get(organization.id, 0),
                "clients": client_counts.get(organization.id, 0),
                "assets": asset_counts.get(organization.id, 0),
                "contracts": contract_counts.get(organization.id, 0),
                "push_devices": push_counts.get(organization.id, 0),
            }
        )
    return rows


def _delete_contracts(organization_id):
    PushNotificationLog.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
    contracts = Contract.query.filter_by(organization_id=organization_id).all()
    for contract in contracts:
        db.session.delete(contract)
    db.session.flush()
    Asset.query.filter_by(organization_id=organization_id).update(
        {Asset.status: "available"}, synchronize_session=False
    )


def _clear_collections(organization_id):
    PushNotificationLog.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
    contracts = Contract.query.filter_by(organization_id=organization_id).all()
    for contract in contracts:
        for payment in list(contract.payments):
            db.session.delete(payment)
        for installment in contract.installments:
            installment.paid_amount = Decimal("0.00")
            installment.late_fee_amount = Decimal("0.00")
            installment.late_fee_paid = Decimal("0.00")
            installment.principal_paid_at = None
            installment.paid_at = None
        if Decimal(str(contract.total_amount or 0)) > Decimal(str(contract.down_payment or 0)):
            contract.status = "active"
        else:
            contract.status = "completed"
    db.session.flush()
    for asset in Asset.query.filter_by(organization_id=organization_id).all():
        if asset.status == "maintenance" and asset.committed_quantity == 0:
            continue
        if asset.available_quantity > 0:
            asset.status = "available"
        elif any(c.status == "active" for c in asset.contracts):
            asset.status = "on_loan"
        elif any(c.status == "completed" and c.deal_type == "credit_sale" for c in asset.contracts):
            asset.status = "sold"
        else:
            asset.status = "available"
    db.session.flush()


def _clear_module(organization_id, module):
    if module == "collections":
        _clear_collections(organization_id)
        return "Cobros y pagos"
    if module == "contracts":
        _delete_contracts(organization_id)
        return "Acuerdos"
    if module == "assets":
        _delete_contracts(organization_id)
        Asset.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
        return "Bienes"
    if module == "clients":
        _delete_contracts(organization_id)
        Client.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
        return "Clientes"
    if module == "notifications":
        PushNotificationLog.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
        return "Historial de alertas"
    if module == "push_devices":
        PushSubscription.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
        return "Dispositivos Push"
    abort(400, description="Modulo no valido.")


def _clear_company_content(organization_id):
    PushNotificationLog.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
    PushSubscription.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
    _delete_contracts(organization_id)
    Client.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
    Asset.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
    db.session.flush()


@admin_bp.get("")
@superadmin_required
def dashboard():
    organizations = [
        organization
        for organization in Organization.query.order_by(Organization.created_at.desc()).all()
        if organization.id != current_user.organization_id
    ]
    all_rows = _rows_for_organizations(organizations)

    today = date.today()
    active_rows = [row for row in all_rows if row["status"] == "active"]
    mrr = sum(
        (
            row["amount"] / Decimal(max(row["plan"].billing_interval_months, 1))
            for row in active_rows
            if row["plan"] is not None and row["plan"].currency == "DOP"
        ),
        Decimal("0.00"),
    )
    due_soon = sum(
        1
        for row in all_rows
        if row["subscription"]
        and row["subscription"].current_period_end
        and today <= row["subscription"].current_period_end <= today + timedelta(days=7)
        and row["status"] in {"active", "trial"}
    )
    attention = sum(1 for row in all_rows if row["status"] in {"pending", "past_due", "expired", "suspended"})
    month_start = datetime(today.year, today.month, 1)
    collected_month = (
        db.session.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0))
        .join(OrganizationSubscription, SubscriptionPayment.subscription_id == OrganizationSubscription.id)
        .filter(OrganizationSubscription.organization_id != current_user.organization_id)
        .filter(SubscriptionPayment.paid_at >= month_start)
        .filter(SubscriptionPayment.currency == "DOP")
        .filter(SubscriptionPayment.voided_at.is_(None))
        .scalar()
        or Decimal("0.00")
    )

    query_text = (request.args.get("q") or "").strip().lower()
    status_filter = (request.args.get("status") or "all").strip().lower()
    plan_filter = (request.args.get("plan") or "all").strip()
    sort = (request.args.get("sort") or "recent").strip().lower()

    rows = all_rows
    if query_text:
        rows = [
            row
            for row in rows
            if query_text in row["organization"].name.lower()
            or (row["owner"] and query_text in row["owner"].name.lower())
            or (row["owner"] and query_text in row["owner"].email.lower())
        ]
    if status_filter != "all":
        rows = [row for row in rows if row["status"] == status_filter]
    if plan_filter != "all":
        if plan_filter == "none":
            rows = [row for row in rows if row["plan"] is None]
        else:
            try:
                plan_id = int(plan_filter)
                rows = [row for row in rows if row["plan"] and row["plan"].id == plan_id]
            except ValueError:
                plan_filter = "all"

    if sort == "name":
        rows.sort(key=lambda row: row["organization"].name.lower())
    elif sort == "renewal":
        rows.sort(
            key=lambda row: (
                row["subscription"].current_period_end if row["subscription"] and row["subscription"].current_period_end else date.max,
                row["organization"].name.lower(),
            )
        )
    elif sort == "status":
        rows.sort(key=lambda row: (row["status"], row["organization"].name.lower()))
    else:
        rows.sort(key=lambda row: row["organization"].created_at, reverse=True)

    plans = SubscriptionPlan.query.order_by(SubscriptionPlan.is_active.desc(), SubscriptionPlan.price.asc()).all()
    recent_activity = AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc()).limit(6).all()
    return render_template(
        "admin/index.html",
        rows=rows,
        total_companies=len(all_rows),
        active_subscriptions=len(active_rows),
        due_soon=due_soon,
        attention=attention,
        mrr=mrr,
        collected_month=Decimal(str(collected_month)),
        plans=plans,
        recent_activity=recent_activity,
        status_labels=STATUS_LABELS,
        query_text=query_text,
        status_filter=status_filter,
        plan_filter=plan_filter,
        sort=sort,
    )


@admin_bp.route("/organizations/new", methods=["GET", "POST"])
@superadmin_required
def create_company():
    plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.price.asc()).all()
    if request.method == "POST":
        business_name = (request.form.get("business_name") or "").strip()
        owner_name = (request.form.get("owner_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        status = (request.form.get("status") or "pending").strip().lower()
        errors = []
        if len(business_name) < 2:
            errors.append("Escribe el nombre de la empresa.")
        if len(owner_name) < 2:
            errors.append("Escribe el nombre del propietario.")
        if "@" not in email or "." not in email:
            errors.append("Escribe un correo valido.")
        if User.query.filter_by(email=email).first():
            errors.append("Ese correo ya esta registrado.")
        if len(password) < 8:
            errors.append("La contrasena inicial debe tener al menos 8 caracteres.")
        if status not in SUBSCRIPTION_STATUSES:
            errors.append("Estado de suscripcion no valido.")

        try:
            plan = _plan_or_none(request.form.get("plan_id"), active_only=True)
            amount_override = _parse_decimal(request.form.get("amount_override"), field_name="Precio personalizado")
            period_end = _parse_date(request.form.get("current_period_end"), field_name="Vencimiento")
        except ValueError as exc:
            errors.append(str(exc))
            plan = None
            amount_override = None
            period_end = None

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("admin/new_organization.html", plans=plans, status_labels=STATUS_LABELS)

        today = date.today()
        if period_end is None and plan is not None and status in {"active", "trial"}:
            period_end = _period_end(today, plan.billing_interval_months)

        organization = Organization(name=business_name, currency="DOP")
        owner = User(organization=organization, name=owner_name, email=email, role="owner", is_enabled=True)
        owner.set_password(password)
        subscription = OrganizationSubscription(
            organization=organization,
            plan=plan,
            status=status,
            amount_override=amount_override,
            current_period_start=today if status in {"active", "trial"} else None,
            current_period_end=period_end,
        )
        db.session.add_all([organization, owner, subscription])
        db.session.flush()
        _audit(
            "organization.create",
            f"Empresa {organization.name} creada desde superadmin.",
            organization_id=organization.id,
            target_id=organization.id,
        )
        db.session.commit()
        flash(f"{organization.name} fue creada y ya puedes administrarla.", "success")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id))

    return render_template("admin/new_organization.html", plans=plans, status_labels=STATUS_LABELS)


@admin_bp.get("/organizations/<int:organization_id>")
@superadmin_required
def organization_detail(organization_id):
    organization = _organization_or_404(organization_id)
    subscription = organization.subscription
    effective_status = subscription.effective_status if subscription else "pending"
    plans = SubscriptionPlan.query.order_by(SubscriptionPlan.is_active.desc(), SubscriptionPlan.price.asc()).all()
    counts = {
        "users": User.query.filter_by(organization_id=organization.id).count(),
        "clients": Client.query.filter_by(organization_id=organization.id).count(),
        "assets": Asset.query.filter_by(organization_id=organization.id).count(),
        "contracts": Contract.query.filter_by(organization_id=organization.id).count(),
        "push_devices": PushSubscription.query.filter_by(organization_id=organization.id, is_active=True).count(),
    }
    users = User.query.filter_by(organization_id=organization.id).order_by(User.role.asc(), User.created_at.asc()).all()
    recent_activity = (
        AdminAuditLog.query.filter_by(organization_id=organization.id)
        .order_by(AdminAuditLog.created_at.desc())
        .limit(12)
        .all()
    )
    payments = list(subscription.payments[:10]) if subscription else []
    return render_template(
        "admin/organization.html",
        organization=organization,
        subscription=subscription,
        effective_status=effective_status,
        status_labels=STATUS_LABELS,
        status_tones=STATUS_TONES,
        plans=plans,
        counts=counts,
        users=users,
        payments=payments,
        recent_activity=recent_activity,
    )


@admin_bp.post("/organizations/<int:organization_id>/profile")
@superadmin_required
def update_company(organization_id):
    organization = _organization_or_404(organization_id)
    name = (request.form.get("name") or "").strip()
    if len(name) < 2:
        flash("El nombre de la empresa debe tener al menos 2 caracteres.", "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="company"))
    old_name = organization.name
    organization.name = name
    _audit(
        "organization.update",
        f"Empresa actualizada: {old_name} -> {name}.",
        organization_id=organization.id,
        target_id=organization.id,
    )
    db.session.commit()
    flash("Datos de la empresa actualizados.", "success")
    return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="company"))


@admin_bp.post("/organizations/<int:organization_id>/subscription")
@superadmin_required
def update_subscription(organization_id):
    organization = _organization_or_404(organization_id)
    subscription = _subscription_or_create(organization)
    errors = []
    status = (request.form.get("status") or "pending").strip().lower()
    if status not in SUBSCRIPTION_STATUSES:
        errors.append("Estado de suscripcion no valido.")
    try:
        plan = _plan_or_none(request.form.get("plan_id"))
        amount_override = _parse_decimal(request.form.get("amount_override"), field_name="Precio personalizado")
        period_start = _parse_date(request.form.get("current_period_start"), field_name="Inicio del periodo")
        period_end = _parse_date(request.form.get("current_period_end"), field_name="Fin del periodo")
        grace_ends_at = _parse_date(request.form.get("grace_ends_at"), field_name="Fin de gracia")
    except ValueError as exc:
        errors.append(str(exc))
        plan = subscription.plan
        amount_override = subscription.amount_override
        period_start = subscription.current_period_start
        period_end = subscription.current_period_end
        grace_ends_at = subscription.grace_ends_at

    if period_start and period_end and period_start > period_end:
        errors.append("El inicio del periodo no puede ser posterior al vencimiento.")
    if grace_ends_at and period_end and grace_ends_at < period_end:
        errors.append("La gracia no puede terminar antes del vencimiento.")
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="subscription"))

    subscription.plan = plan
    subscription.status = status
    subscription.amount_override = amount_override
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end
    subscription.grace_ends_at = grace_ends_at
    subscription.notes = (request.form.get("notes") or "").strip()[:2000] or None
    _audit(
        "subscription.update",
        f"Suscripcion de {organization.name} actualizada.",
        organization_id=organization.id,
        target_type="subscription",
        target_id=subscription.id,
        detail=f"status={status}; plan={plan.name if plan else 'sin plan'}; end={period_end or '-'}",
    )
    db.session.commit()
    flash("Suscripcion actualizada.", "success")
    return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="subscription"))


@admin_bp.post("/organizations/<int:organization_id>/subscription/extend")
@superadmin_required
def extend_subscription(organization_id):
    organization = _organization_or_404(organization_id)
    subscription = _subscription_or_create(organization)
    try:
        days = int(request.form.get("days") or "30")
    except ValueError:
        days = 0
    if not 1 <= days <= 3650:
        flash("La extension debe estar entre 1 y 3650 dias.", "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="subscription"))

    today = date.today()
    base = subscription.current_period_end if subscription.current_period_end and subscription.current_period_end >= today else today
    if subscription.current_period_start is None:
        subscription.current_period_start = today
    subscription.current_period_end = base + timedelta(days=days)
    subscription.status = "active"
    if subscription.grace_ends_at and subscription.grace_ends_at < subscription.current_period_end:
        subscription.grace_ends_at = None
    _audit(
        "subscription.extend",
        f"Suscripcion de {organization.name} extendida {days} dias.",
        organization_id=organization.id,
        target_type="subscription",
        target_id=subscription.id,
        detail=f"nuevo_vencimiento={subscription.current_period_end.isoformat()}",
    )
    db.session.commit()
    flash(f"Suscripcion extendida {days} dias.", "success")
    return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="subscription"))


@admin_bp.post("/organizations/<int:organization_id>/subscription/payment")
@superadmin_required
def record_subscription_payment(organization_id):
    organization = _organization_or_404(organization_id)
    subscription = _subscription_or_create(organization)
    try:
        amount = _parse_decimal(request.form.get("amount"), field_name="Monto", allow_empty=True)
        months = int(request.form.get("months") or (subscription.plan.billing_interval_months if subscription.plan else 1))
    except (ValueError, TypeError) as exc:
        flash(str(exc) if str(exc) else "Datos de pago no validos.", "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="billing"))
    if not 1 <= months <= 24:
        flash("El periodo del pago debe estar entre 1 y 24 meses.", "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="billing"))
    if amount is None:
        amount = subscription.effective_amount
    if amount <= 0:
        flash("Indica un monto mayor que cero para registrar el pago.", "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="billing"))

    today = date.today()
    start = (
        subscription.current_period_end + timedelta(days=1)
        if subscription.current_period_end and subscription.current_period_end >= today
        else today
    )
    end = _period_end(start, months)
    payment = SubscriptionPayment(
        subscription=subscription,
        amount=amount,
        currency=subscription.plan.currency if subscription.plan else organization.currency,
        method=(request.form.get("method") or "cash").strip()[:30],
        reference=(request.form.get("reference") or "").strip()[:120] or None,
        note=(request.form.get("note") or "").strip()[:240] or None,
        period_start=start,
        period_end=end,
        previous_period_start=subscription.current_period_start,
        previous_period_end=subscription.current_period_end,
        previous_status=subscription.status,
        paid_at=datetime.utcnow(),
        created_by_user_id=current_user.id,
    )
    subscription.status = "active"
    subscription.current_period_start = start
    subscription.current_period_end = end
    subscription.grace_ends_at = None
    subscription.last_payment_at = payment.paid_at
    db.session.add(payment)
    db.session.flush()
    _audit(
        "subscription.payment",
        f"Pago de suscripcion registrado para {organization.name}: {amount:.2f} {payment.currency}.",
        organization_id=organization.id,
        target_type="subscription_payment",
        target_id=payment.id,
        detail=f"period={start.isoformat()}..{end.isoformat()}; method={payment.method}; reference={payment.reference or '-'}",
    )
    db.session.commit()
    flash("Pago registrado y periodo renovado.", "success")
    return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="billing"))


@admin_bp.post("/organizations/<int:organization_id>/subscription/payments/<int:payment_id>/void")
@superadmin_required
def void_subscription_payment(organization_id, payment_id):
    organization = _organization_or_404(organization_id)
    subscription = organization.subscription
    payment = db.session.get(SubscriptionPayment, payment_id)
    if subscription is None or payment is None or payment.subscription_id != subscription.id:
        abort(404)
    if payment.voided_at is not None:
        flash("Ese pago ya estaba anulado.", "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="billing"))
    reason = (request.form.get("reason") or "").strip()[:240]
    if len(reason) < 3:
        flash("Escribe el motivo de la anulacion.", "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="billing"))

    payment.voided_at = datetime.utcnow()
    payment.voided_by_user_id = current_user.id
    payment.void_reason = reason
    if subscription.current_period_start == payment.period_start and subscription.current_period_end == payment.period_end:
        subscription.current_period_start = payment.previous_period_start
        subscription.current_period_end = payment.previous_period_end
        subscription.status = payment.previous_status or "pending"
        previous_payment = (
            SubscriptionPayment.query
            .filter_by(subscription_id=subscription.id)
            .filter(SubscriptionPayment.id != payment.id, SubscriptionPayment.voided_at.is_(None))
            .order_by(SubscriptionPayment.paid_at.desc())
            .first()
        )
        subscription.last_payment_at = previous_payment.paid_at if previous_payment else None
    _audit(
        "subscription.payment_void",
        f"Pago de suscripcion anulado para {organization.name}: {payment.amount:.2f} {payment.currency}.",
        organization_id=organization.id,
        target_type="subscription_payment",
        target_id=payment.id,
        detail=f"motivo={reason}",
    )
    db.session.commit()
    flash("Pago anulado. El historial se conservo para auditoria.", "success")
    return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="billing"))


@admin_bp.post("/organizations/<int:organization_id>/users")
@superadmin_required
def create_user(organization_id):
    organization = _organization_or_404(organization_id)
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    role = (request.form.get("role") or "staff").strip().lower()
    errors = []
    if len(name) < 2:
        errors.append("Escribe el nombre del usuario.")
    if "@" not in email or "." not in email:
        errors.append("Escribe un correo valido.")
    if User.query.filter_by(email=email).first():
        errors.append("Ese correo ya esta registrado.")
    if len(password) < 8:
        errors.append("La contrasena debe tener al menos 8 caracteres.")
    if role not in {"owner", "staff"}:
        errors.append("Rol no valido.")
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="users"))

    user = User(organization=organization, name=name, email=email, role=role, is_enabled=True)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    _audit(
        "user.create",
        f"Usuario {user.email} creado en {organization.name}.",
        organization_id=organization.id,
        target_type="user",
        target_id=user.id,
    )
    db.session.commit()
    flash("Usuario creado.", "success")
    return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="users"))


@admin_bp.post("/organizations/<int:organization_id>/users/<int:user_id>")
@superadmin_required
def update_user(organization_id, user_id):
    organization = _organization_or_404(organization_id)
    user = db.session.get(User, user_id)
    if user is None or user.organization_id != organization.id:
        abort(404)
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    role = (request.form.get("role") or user.role or "staff").strip().lower()
    errors = []
    if len(name) < 2:
        errors.append("Escribe el nombre del usuario.")
    if "@" not in email or "." not in email:
        errors.append("Escribe un correo valido.")
    existing = User.query.filter(User.email == email, User.id != user.id).first()
    if existing:
        errors.append("Ese correo ya pertenece a otra cuenta.")
    if role not in {"owner", "staff"}:
        errors.append("Rol no valido.")
    if user.role == "owner" and role != "owner":
        owner_count = User.query.filter_by(organization_id=organization.id, role="owner").count()
        if owner_count <= 1:
            errors.append("La empresa debe conservar al menos un propietario.")
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="users"))

    old_email = user.email
    user.name = name
    user.email = email
    user.role = role
    _audit(
        "user.update",
        f"Usuario {old_email} actualizado en {organization.name}.",
        organization_id=organization.id,
        target_type="user",
        target_id=user.id,
        detail=f"email={email}; role={role}",
    )
    db.session.commit()
    flash("Usuario actualizado.", "success")
    return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="users"))


@admin_bp.post("/organizations/<int:organization_id>/users/<int:user_id>/toggle")
@superadmin_required
def toggle_user(organization_id, user_id):
    organization = _organization_or_404(organization_id)
    user = db.session.get(User, user_id)
    if user is None or user.organization_id != organization.id:
        abort(404)
    user.is_enabled = not user.is_enabled
    action = "user.enable" if user.is_enabled else "user.disable"
    label = "habilitado" if user.is_enabled else "deshabilitado"
    _audit(
        action,
        f"Usuario {user.email} {label} en {organization.name}.",
        organization_id=organization.id,
        target_type="user",
        target_id=user.id,
    )
    db.session.commit()
    flash(f"Usuario {label}.", "success")
    return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="users"))


@admin_bp.post("/organizations/<int:organization_id>/users/<int:user_id>/password")
@superadmin_required
def reset_user_password(organization_id, user_id):
    organization = _organization_or_404(organization_id)
    user = db.session.get(User, user_id)
    if user is None or user.organization_id != organization.id:
        abort(404)
    password = request.form.get("password") or ""
    if len(password) < 8:
        flash("La contrasena temporal debe tener al menos 8 caracteres.", "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="users"))
    user.set_password(password)
    _audit(
        "user.password_reset",
        f"Contrasena restablecida para {user.email} en {organization.name}.",
        organization_id=organization.id,
        target_type="user",
        target_id=user.id,
    )
    db.session.commit()
    flash("Contrasena restablecida. No se guardo el valor en el historial.", "success")
    return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="users"))


@admin_bp.post("/organizations/<int:organization_id>/clear")
@superadmin_required
def clear_module(organization_id):
    organization = _organization_or_404(organization_id)
    if not _require_company_confirmation(organization, "clear"):
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="maintenance"))
    module = (request.form.get("module") or "").strip()
    label = _clear_module(organization.id, module)
    _audit(
        "data.clear",
        f"{label} limpiado en {organization.name}.",
        organization_id=organization.id,
        target_type="data",
        target_id=module,
    )
    db.session.commit()
    flash(f"{label} de {organization.name} fue limpiado.", "success")
    return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="maintenance"))


@admin_bp.post("/organizations/<int:organization_id>/reset")
@superadmin_required
def reset_company(organization_id):
    organization = _organization_or_404(organization_id)
    if not _require_company_confirmation(organization, "reset"):
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="maintenance"))
    _clear_company_content(organization.id)
    _audit(
        "organization.reset",
        f"Datos operativos de {organization.name} reiniciados.",
        organization_id=organization.id,
        target_id=organization.id,
    )
    db.session.commit()
    flash(f"{organization.name} quedo vacia. La empresa, suscripcion y usuarios se conservaron.", "success")
    return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="maintenance"))


@admin_bp.post("/organizations/<int:organization_id>/delete")
@superadmin_required
def delete_company(organization_id):
    organization = _organization_or_404(organization_id)
    if not _require_company_confirmation(organization, "delete"):
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="maintenance"))
    if request.form.get("confirm_delete") != "yes":
        flash("Marca la casilla de confirmacion antes de eliminar la empresa.", "error")
        return redirect(url_for("admin.organization_detail", organization_id=organization.id, _anchor="maintenance"))
    name = organization.name

    _audit(
        "organization.delete",
        f"Empresa {name} eliminada por completo.",
        organization_id=organization.id,
        target_id=organization.id,
    )
    PushNotificationLog.query.filter_by(organization_id=organization.id).delete(synchronize_session=False)
    PushSubscription.query.filter_by(organization_id=organization.id).delete(synchronize_session=False)
    _delete_contracts(organization.id)
    Client.query.filter_by(organization_id=organization.id).delete(synchronize_session=False)
    Asset.query.filter_by(organization_id=organization.id).delete(synchronize_session=False)
    User.query.filter_by(organization_id=organization.id).delete(synchronize_session=False)
    if organization.subscription is not None:
        db.session.delete(organization.subscription)
        db.session.flush()
    db.session.delete(organization)
    db.session.commit()

    flash(f"Empresa {name} eliminada por completo.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.get("/plans")
@superadmin_required
def plans():
    plan_rows = []
    for plan in SubscriptionPlan.query.order_by(SubscriptionPlan.is_active.desc(), SubscriptionPlan.price.asc()).all():
        subscriptions = OrganizationSubscription.query.filter_by(plan_id=plan.id).all()
        plan_rows.append(
            {
                "plan": plan,
                "subscriptions": len(subscriptions),
                "active_subscriptions": sum(1 for item in subscriptions if item.effective_status == "active"),
            }
        )
    return render_template("admin/plans.html", plan_rows=plan_rows)


@admin_bp.post("/plans")
@superadmin_required
def create_plan():
    name = (request.form.get("name") or "").strip()
    currency = (request.form.get("currency") or "DOP").strip().upper()[:8]
    errors = []
    if len(name) < 2:
        errors.append("Escribe el nombre del plan.")
    try:
        price = _parse_decimal(request.form.get("price"), field_name="Precio", allow_empty=False)
        months = int(request.form.get("billing_interval_months") or "1")
    except (ValueError, TypeError) as exc:
        errors.append(str(exc) if str(exc) else "Datos del plan no validos.")
        price = Decimal("0.00")
        months = 1
    if not 1 <= months <= 24:
        errors.append("El intervalo debe estar entre 1 y 24 meses.")
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("admin.plans"))

    plan = SubscriptionPlan(
        code=_unique_plan_code(name),
        name=name,
        price=price,
        currency=currency or "DOP",
        billing_interval_months=months,
        is_active=True,
    )
    db.session.add(plan)
    db.session.flush()
    _audit(
        "plan.create",
        f"Plan {plan.name} creado por {price:.2f} {plan.currency}.",
        target_type="subscription_plan",
        target_id=plan.id,
    )
    db.session.commit()
    flash("Plan creado.", "success")
    return redirect(url_for("admin.plans"))


@admin_bp.post("/plans/<int:plan_id>")
@superadmin_required
def update_plan(plan_id):
    plan = db.session.get(SubscriptionPlan, plan_id)
    if plan is None:
        abort(404)
    name = (request.form.get("name") or "").strip()
    currency = (request.form.get("currency") or plan.currency or "DOP").strip().upper()[:8]
    errors = []
    if len(name) < 2:
        errors.append("Escribe el nombre del plan.")
    try:
        price = _parse_decimal(request.form.get("price"), field_name="Precio", allow_empty=False)
        months = int(request.form.get("billing_interval_months") or "1")
    except (ValueError, TypeError) as exc:
        errors.append(str(exc) if str(exc) else "Datos del plan no validos.")
        price = plan.price
        months = plan.billing_interval_months
    if not 1 <= months <= 24:
        errors.append("El intervalo debe estar entre 1 y 24 meses.")
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("admin.plans"))

    plan.name = name
    plan.code = _unique_plan_code(name, ignore_id=plan.id)
    plan.price = price
    plan.currency = currency or "DOP"
    plan.billing_interval_months = months
    _audit(
        "plan.update",
        f"Plan {plan.name} actualizado.",
        target_type="subscription_plan",
        target_id=plan.id,
    )
    db.session.commit()
    flash("Plan actualizado.", "success")
    return redirect(url_for("admin.plans"))


@admin_bp.post("/plans/<int:plan_id>/toggle")
@superadmin_required
def toggle_plan(plan_id):
    plan = db.session.get(SubscriptionPlan, plan_id)
    if plan is None:
        abort(404)
    plan.is_active = not plan.is_active
    action = "plan.restore" if plan.is_active else "plan.archive"
    state = "reactivado" if plan.is_active else "archivado"
    _audit(
        action,
        f"Plan {plan.name} {state}.",
        target_type="subscription_plan",
        target_id=plan.id,
    )
    db.session.commit()
    flash(f"Plan {state}.", "success")
    return redirect(url_for("admin.plans"))


@admin_bp.get("/activity")
@superadmin_required
def activity():
    query_text = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "all").strip().lower()
    logs = AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc()).limit(300).all()
    if query_text:
        logs = [
            log
            for log in logs
            if query_text in (log.summary or "").lower()
            or query_text in (log.action or "").lower()
            or query_text in (log.detail or "").lower()
        ]
    if category != "all":
        logs = [log for log in logs if (log.action or "").startswith(f"{category}.")]
    actor_ids = {log.actor_user_id for log in logs if log.actor_user_id}
    actors = {user.id: user for user in User.query.filter(User.id.in_(actor_ids)).all()} if actor_ids else {}
    return render_template(
        "admin/audit.html",
        logs=logs,
        actors=actors,
        query_text=query_text,
        category=category,
    )


@admin_bp.get("/subscriptions.csv")
@superadmin_required
def export_subscriptions():
    organizations = [
        organization
        for organization in Organization.query.order_by(Organization.name.asc()).all()
        if organization.id != current_user.organization_id
    ]
    rows = _rows_for_organizations(organizations)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "empresa_id",
            "empresa",
            "propietario",
            "correo",
            "estado",
            "plan",
            "monto",
            "moneda",
            "inicio_periodo",
            "vence",
            "gracia_hasta",
            "usuarios",
            "clientes",
            "acuerdos",
        ]
    )
    for row in rows:
        subscription = row["subscription"]
        writer.writerow(
            [
                row["organization"].id,
                row["organization"].name,
                row["owner"].name if row["owner"] else "",
                row["owner"].email if row["owner"] else "",
                row["status"],
                row["plan"].name if row["plan"] else "",
                f"{row['amount']:.2f}",
                row["plan"].currency if row["plan"] else row["organization"].currency,
                subscription.current_period_start.isoformat() if subscription and subscription.current_period_start else "",
                subscription.current_period_end.isoformat() if subscription and subscription.current_period_end else "",
                subscription.grace_ends_at.isoformat() if subscription and subscription.grace_ends_at else "",
                row["users"],
                row["clients"],
                row["contracts"],
            ]
        )
    filename = f"cuotago-suscripciones-{date.today().isoformat()}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
