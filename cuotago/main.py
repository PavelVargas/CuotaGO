import calendar as pycalendar
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import quote
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .extensions import db
from .models import Asset, Client, Contract, Installment, Payment

main_bp = Blueprint("main", __name__)
CENT = Decimal("0.01")


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


def generate_installments(contract):
    remaining = money_decimal(contract.total_amount) - money_decimal(contract.down_payment)
    installment_value = money_decimal(contract.installment_amount)
    due = contract.first_due_date
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


def scoped_client(client_id):
    return Client.query.filter_by(id=client_id, organization_id=current_user.organization_id).first_or_404()


def scoped_asset(asset_id):
    return Asset.query.filter_by(id=asset_id, organization_id=current_user.organization_id).first_or_404()


def scoped_contract(contract_id):
    return Contract.query.filter_by(id=contract_id, organization_id=current_user.organization_id).first_or_404()


def tenant_installments(active_only=True):
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
                Installment.paid_amount < Installment.amount,
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


def whatsapp_link(client, contract=None, installment=None):
    digits = re.sub(r"\D", "", client.phone or "")
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) < 10:
        return ""

    message = f"Hola {client.full_name}, te escribimos para recordarte tu pago"
    if contract:
        message += f" del acuerdo {contract.code or ''}"
    if installment:
        message += f" por {format_money(installment.remaining)}, con fecha {installment.due_date.strftime('%d/%m/%Y')}"
    message += ". Gracias."
    return f"https://wa.me/{digits}?text={quote(message)}"


@main_bp.app_context_processor
def inject_helpers():
    return {
        "money": format_money,
        "asset_kind_label": asset_kind_label,
        "asset_status_label": asset_status_label,
        "contract_status_label": contract_status_label,
        "frequency_label": frequency_label,
        "deal_type_label": deal_type_label,
        "wa_link": whatsapp_link,
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

    return render_template(
        "dashboard.html",
        overdue=overdue[:5],
        due_today=due_today[:5],
        upcoming=upcoming[:5],
        overdue_count=len(overdue),
        due_today_count=len(due_today),
        active_count=len(active_contracts),
        receivable=receivable,
        overdue_total=overdue_total,
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
        db.session.commit()
        flash("Cliente creado.", "success")
        return redirect(url_for("main.clients"))

    return render_template("clients/form.html", client=None)


@main_bp.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
@login_required
def client_edit(client_id):
    client = scoped_client(client_id)
    if request.method == "POST":
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
        db.session.commit()
        flash("Cliente actualizado.", "success")
        return redirect(url_for("main.clients"))
    return render_template("clients/form.html", client=client)


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
    if status:
        query = query.filter_by(status=status)
    items = query.order_by(Asset.created_at.desc()).all()
    return render_template("assets/list.html", assets=items, q=q, status=status)


@main_bp.route("/assets/new", methods=["GET", "POST"])
@login_required
def asset_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        value = parse_money(request.form.get("estimated_value"), Decimal("0.00"))
        kind = request.form.get("kind", "other")
        if len(name) < 2:
            flash("Escribe un nombre para el bien.", "error")
            return render_template("assets/form.html", asset=None)
        if kind not in {"car", "phone", "motorcycle", "appliance", "computer", "other"}:
            kind = "other"

        asset = Asset(
            organization_id=current_user.organization_id,
            kind=kind,
            name=name,
            brand=request.form.get("brand", "").strip(),
            model=request.form.get("model", "").strip(),
            identifier=request.form.get("identifier", "").strip(),
            serial_number=request.form.get("serial_number", "").strip(),
            estimated_value=value or Decimal("0.00"),
            status="available",
            notes=request.form.get("notes", "").strip(),
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
        asset.notes = request.form.get("notes", "").strip()
        if asset.status not in {"on_loan", "sold"}:
            requested_status = request.form.get("status", "available")
            asset.status = requested_status if requested_status in {"available", "maintenance"} else "available"
        db.session.commit()
        flash("Bien actualizado.", "success")
        return redirect(url_for("main.assets"))
    return render_template("assets/form.html", asset=asset)


@main_bp.get("/contracts")
@login_required
def contracts():
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
    assets_list = Asset.query.filter_by(
        organization_id=current_user.organization_id,
        status="available",
    ).order_by(Asset.name.asc()).all()

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
                status="available",
            ).first()

        client_name = request.form.get("client_name", "").strip()
        client_phone = request.form.get("client_phone", "").strip()
        asset_name = request.form.get("asset_name", "").strip()
        asset_kind = request.form.get("asset_kind", "other").strip()
        asset_identifier = request.form.get("asset_identifier", "").strip()

        deal_type = request.form.get("deal_type", "credit_sale")
        total = parse_money(request.form.get("total_amount"))
        down = parse_money(request.form.get("down_payment"), Decimal("0.00"))
        installment = parse_money(request.form.get("installment_amount"))
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
        if total is None or total <= 0:
            errors.append("El total debe ser mayor que cero.")
        if down is None or down < 0:
            errors.append("El inicial no puede ser negativo.")
        if total is not None and down is not None and down > total:
            errors.append("El inicial no puede ser mayor al total.")
        if installment is None or installment <= 0:
            errors.append("La cuota debe ser mayor que cero.")
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
                estimated_value=total or Decimal("0.00"),
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
            down_payment=down,
            installment_amount=installment,
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
            generate_installments(contract)
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

        asset.status = "on_loan"
        if total - down <= Decimal("0.009"):
            contract.status = "completed"
            asset.status = "sold" if deal_type == "credit_sale" else "available"
        db.session.commit()
        flash("Listo. Acuerdo creado y fechas calculadas.", "success")
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
    if method not in {"cash", "transfer", "card", "other"}:
        method = "other"

    payment = Payment(
        contract=contract,
        amount=amount,
        method=method,
        note=request.form.get("note", "").strip(),
        paid_at=datetime.utcnow(),
    )
    db.session.add(payment)

    to_allocate = amount
    for installment in contract.installments:
        if to_allocate <= Decimal("0.009"):
            break
        due_remaining = installment.remaining
        if due_remaining <= Decimal("0.009"):
            continue
        applied = min(due_remaining, to_allocate)
        installment.paid_amount = money_decimal(installment.paid_amount) + applied
        if installment.remaining <= Decimal("0.009"):
            installment.paid_at = datetime.utcnow()
        to_allocate -= applied

    projected_balance = balance_before - amount
    if projected_balance <= Decimal("0.009"):
        contract.status = "completed"
        contract.asset.status = "sold" if contract.deal_type == "credit_sale" else "available"

    db.session.commit()
    flash(f"Pago de {format_money(amount)} registrado.", "success")
    next_url = request.form.get("next", "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for("main.contract_detail", contract_id=contract.id))


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
    start = local_today()
    end = start + timedelta(days=60)
    items = [
        i
        for i in tenant_installments(active_only=True)
        if i.remaining > Decimal("0.009") and start <= i.due_date <= end
    ]
    grouped = {}
    for installment in items:
        grouped.setdefault(installment.due_date, []).append(installment)
    return render_template("calendar/list.html", grouped=grouped, start=start, end=end)


@main_bp.get("/reports")
@login_required
def reports():
    org_id = current_user.organization_id
    contracts_all = Contract.query.filter_by(organization_id=org_id).all()
    active = [c for c in contracts_all if c.status == "active"]
    completed = [c for c in contracts_all if c.status == "completed"]
    clients_count = Client.query.filter_by(organization_id=org_id).count()
    assets_count = Asset.query.filter_by(organization_id=org_id).count()

    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_payments = (
        Payment.query.join(Contract)
        .filter(Contract.organization_id == org_id, Payment.paid_at >= month_start)
        .all()
    )
    month_collected = sum((money_decimal(p.amount) for p in monthly_payments), Decimal("0.00"))
    receivable = sum((c.balance for c in active), Decimal("0.00"))
    installments = tenant_installments(active_only=True)
    overdue = [i for i in installments if i.remaining > Decimal("0.009") and i.due_date < local_today()]
    overdue_total = sum((i.remaining for i in overdue), Decimal("0.00"))

    return render_template(
        "reports/index.html",
        active_count=len(active),
        completed_count=len(completed),
        clients_count=clients_count,
        assets_count=assets_count,
        month_collected=month_collected,
        receivable=receivable,
        overdue_total=overdue_total,
        overdue_count=len(overdue),
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
