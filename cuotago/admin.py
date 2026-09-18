from functools import wraps
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .models import (
    Asset,
    Client,
    Contract,
    Installment,
    Organization,
    Payment,
    PushNotificationLog,
    PushSubscription,
    User,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/superadmin")


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
        abort(400, description="La organizacion del superadmin no puede borrarse desde este panel.")
    return organization


def _contracts_for_org(organization_id):
    return Contract.query.filter_by(organization_id=organization_id).all()


def _delete_contracts(organization_id):
    PushNotificationLog.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
    contracts = _contracts_for_org(organization_id)
    for contract in contracts:
        db.session.delete(contract)
    db.session.flush()
    Asset.query.filter_by(organization_id=organization_id).update(
        {Asset.status: "available"}, synchronize_session=False
    )


def _clear_collections(organization_id):
    PushNotificationLog.query.filter_by(organization_id=organization_id).delete(synchronize_session=False)
    contracts = _contracts_for_org(organization_id)
    for contract in contracts:
        for payment in list(contract.payments):
            db.session.delete(payment)
        for installment in contract.installments:
            installment.paid_amount = Decimal("0.00")
            installment.paid_at = None
        if Decimal(str(contract.total_amount or 0)) > Decimal(str(contract.down_payment or 0)):
            contract.status = "active"
            if contract.asset:
                contract.asset.status = "on_loan"
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
    organizations = Organization.query.order_by(Organization.created_at.desc()).all()
    rows = []
    for organization in organizations:
        if organization.id == current_user.organization_id:
            continue
        rows.append({
            "organization": organization,
            "users": User.query.filter_by(organization_id=organization.id).count(),
            "clients": Client.query.filter_by(organization_id=organization.id).count(),
            "assets": Asset.query.filter_by(organization_id=organization.id).count(),
            "contracts": Contract.query.filter_by(organization_id=organization.id).count(),
            "push_devices": PushSubscription.query.filter_by(organization_id=organization.id, is_active=True).count(),
        })
    return render_template("admin/index.html", rows=rows)


@admin_bp.post("/organizations/<int:organization_id>/clear")
@superadmin_required
def clear_module(organization_id):
    organization = _organization_or_404(organization_id)
    module = (request.form.get("module") or "").strip()
    label = _clear_module(organization.id, module)
    db.session.commit()
    flash(f"{label} de {organization.name} fue limpiado.", "success")
    return redirect(url_for("admin.dashboard", open_org=organization.id))


@admin_bp.post("/organizations/<int:organization_id>/reset")
@superadmin_required
def reset_company(organization_id):
    organization = _organization_or_404(organization_id)
    _clear_company_content(organization.id)
    db.session.commit()
    flash(f"{organization.name} quedo vacia. La empresa y sus usuarios se conservaron.", "success")
    return redirect(url_for("admin.dashboard", open_org=organization.id))


@admin_bp.post("/organizations/<int:organization_id>/delete")
@superadmin_required
def delete_company(organization_id):
    organization = _organization_or_404(organization_id)
    name = organization.name

    PushNotificationLog.query.filter_by(organization_id=organization.id).delete(synchronize_session=False)
    PushSubscription.query.filter_by(organization_id=organization.id).delete(synchronize_session=False)
    _delete_contracts(organization.id)
    Client.query.filter_by(organization_id=organization.id).delete(synchronize_session=False)
    Asset.query.filter_by(organization_id=organization.id).delete(synchronize_session=False)
    User.query.filter_by(organization_id=organization.id).delete(synchronize_session=False)
    db.session.delete(organization)
    db.session.commit()

    flash(f"Empresa {name} eliminada por completo.", "success")
    return redirect(url_for("admin.dashboard"))
