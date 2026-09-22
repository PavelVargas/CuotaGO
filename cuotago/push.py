import atexit
import base64
import json
import logging
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import Contract, Installment, PushNotificationLog, PushSubscription, User
from .permissions import ROLE_PERMISSIONS, permission_required

push_bp = Blueprint("push", __name__)
log = logging.getLogger(__name__)
COLLECTION_PUSH_ROLES = tuple(
    role for role, permissions in ROLE_PERMISSIONS.items()
    if role != "superadmin" and "collections.view" in permissions
)
_scheduler = None


def _private_key_path(app):
    path = Path(app.instance_path) / "vapid_private.pem"
    encoded = (app.config.get("VAPID_PRIVATE_KEY_B64") or "").strip()
    if encoded:
        try:
            padded = encoded + ("=" * ((4 - len(encoded) % 4) % 4))
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
            if not path.exists() or path.read_bytes() != raw:
                path.write_bytes(raw)
            return str(path)
        except Exception as exc:
            app.logger.error("No se pudo preparar la clave VAPID privada: %s", exc)
    return None


def _push_ready(app):
    return bool(
        app.config.get("PUSH_NOTIFICATIONS_ENABLED")
        and app.config.get("VAPID_PUBLIC_KEY")
        and _private_key_path(app)
    )


def _money(amount, currency):
    value = Decimal(str(amount or 0))
    prefix = {"DOP": "RD$", "USD": "US$", "EUR": "€"}.get(currency or "DOP", f"{currency} ")
    return f"{prefix}{value:,.2f}"


def _sync_installment_late_fee(installment, today_value):
    contract = installment.contract
    rate = Decimal(str(contract.daily_late_interest or 0)).quantize(Decimal("0.01"))
    if rate <= 0 or installment.due_date >= today_value or installment.is_paid:
        return False
    end_day = today_value
    principal_paid_at = installment.principal_paid_at or (installment.paid_at if installment.principal_is_paid else None)
    if principal_paid_at:
        end_day = min(today_value, principal_paid_at.date())
    activation_day = getattr(contract, "late_fee_started_on", None) or contract.start_date
    charge_start = max(installment.due_date, activation_day)
    days_late = max((end_day - charge_start).days, 0)
    target = (rate * days_late).quantize(Decimal("0.01"))
    current = Decimal(str(installment.late_fee_amount or 0)).quantize(Decimal("0.01"))
    if target > current:
        installment.late_fee_amount = target
        return True
    return False


def _subscription_info(subscription):
    return {
        "endpoint": subscription.endpoint,
        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
    }


def send_payload_to_subscription(app, subscription, payload):
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        app.logger.error("pywebpush no esta instalado. Ejecuta pip install -r requirements.txt")
        return False

    private_key = _private_key_path(app)
    if not private_key:
        app.logger.error("Falta la clave VAPID privada.")
        return False

    try:
        webpush(
            subscription_info=_subscription_info(subscription),
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=private_key,
            vapid_claims={"sub": app.config.get("VAPID_SUBJECT", "mailto:admin@cuotago.app")},
            timeout=10,
        )
        subscription.last_seen_at = datetime.utcnow()
        db.session.commit()
        return True
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in {404, 410}:
            subscription.is_active = False
            db.session.commit()
        else:
            db.session.rollback()
        app.logger.warning("Fallo enviando Web Push (%s): %s", status or "sin status", exc)
    except Exception as exc:
        db.session.rollback()
        app.logger.exception("Error inesperado enviando Web Push: %s", exc)
    return False


def send_payload_to_org(app, organization_id, payload):
    subscriptions = (
        PushSubscription.query.join(User, User.id == PushSubscription.user_id)
        .filter(
            PushSubscription.organization_id == organization_id,
            PushSubscription.is_active.is_(True),
            User.is_enabled.is_(True),
            User.role.in_(COLLECTION_PUSH_ROLES),
        ).all()
    )
    sent = 0
    for subscription in subscriptions:
        if send_payload_to_subscription(app, subscription, payload):
            sent += 1
    return sent



def _schedule_test_push(app, subscription_id, delay_seconds=10):
    """Send a real Web Push after a short delay so the user can close/background the PWA."""
    delay_seconds = max(5, min(int(delay_seconds or 10), 30))

    def worker():
        time.sleep(delay_seconds)
        with app.app_context():
            subscription = db.session.get(PushSubscription, subscription_id)
            if not subscription or not subscription.is_active:
                return
            payload = {
                "type": "outside-test",
                "title": "Pago atrasado · Simulación",
                "body": "Cliente de prueba no ha pagado RD$2,500.00. Toca para abrir CuotaGo.",
                "url": "/notifications",
                "tag": f"cuotago-outside-test-{subscription_id}-{int(time.time())}",
            }
            send_payload_to_subscription(app, subscription, payload)

    threading.Thread(target=worker, name=f"cuotago-push-test-{subscription_id}", daemon=True).start()
    return delay_seconds

def overdue_payload(installment, reminder=False):
    contract = installment.contract
    currency = "DOP"
    try:
        from .models import Organization
        organization = db.session.get(Organization, contract.organization_id)
        if organization and organization.currency:
            currency = organization.currency
    except Exception:
        pass

    return {
        "type": "overdue-reminder" if reminder else "overdue",
        "title": "Recordatorio de cobro" if reminder else "Pago atrasado",
        "body": (
            f"Ojo: {contract.client.full_name} todavia te debe {_money(installment.remaining, currency)}. "
            f"Vencio el {installment.due_date.strftime('%d/%m')}."
            if reminder
            else f"{contract.client.full_name} no ha pagado {_money(installment.remaining, currency)}. "
                 f"Vencio el {installment.due_date.strftime('%d/%m')}"
        ),
        # Each repeated reminder gets a fresh notification tag so the operating
        # system alerts again even when the previous reminder used the same debt.
        "tag": f"cuotago-overdue-{installment.id}-{int(time.time())}" if reminder else f"cuotago-overdue-{installment.id}",
        "replaceKey": f"overdue-{installment.id}",
        "installmentId": installment.id,
        "contractId": contract.id,
        "clientName": contract.client.full_name,
        "amount": str(installment.remaining),
    }


def due_today_payload(installment):
    contract = installment.contract
    currency = "DOP"
    try:
        from .models import Organization
        organization = db.session.get(Organization, contract.organization_id)
        if organization and organization.currency:
            currency = organization.currency
    except Exception:
        pass

    return {
        "type": "due_today",
        "title": "Cobro para hoy",
        "body": f"{contract.client.full_name} tiene una cuota de {_money(installment.remaining, currency)} para hoy.",
        "url": f"/contracts/{contract.id}#pay",
        "tag": f"cuotago-due-today-{installment.id}",
        "installmentId": installment.id,
        "contractId": contract.id,
        "clientName": contract.client.full_name,
        "amount": str(installment.remaining),
    }


def scan_overdue_and_notify(app):
    if not _push_ready(app):
        return 0

    tz = ZoneInfo(app.config.get("APP_TIMEZONE", "America/Santo_Domingo"))
    now_local = datetime.now(tz)
    start_hour = int(app.config.get("PUSH_ALERT_START_HOUR", 8))
    end_hour = int(app.config.get("PUSH_ALERT_END_HOUR", 22))
    if now_local.hour < start_hour or now_local.hour >= end_hour:
        return 0

    today_local = now_local.date()
    now_utc = datetime.utcnow()
    repeat_hours = max(1, int(app.config.get("PUSH_OVERDUE_REPEAT_HOURS", 2)))
    repeat_after = timedelta(hours=repeat_hours)
    with app.app_context():
        due_today = (
            Installment.query.join(Contract)
            .filter(Contract.status == "active", Installment.due_date == today_local)
            .order_by(Installment.id.asc())
            .all()
        )
        candidates = (
            Installment.query.join(Contract)
            .filter(Contract.status == "active", Installment.due_date < today_local)
            .order_by(Installment.due_date.asc())
            .all()
        )
        sent_events = 0
        fees_changed = False

        # A cuota due today is pushed once per device/org, even when the PWA is closed.
        for installment in due_today:
            if installment.remaining <= Decimal("0.009"):
                continue
            exists = PushNotificationLog.query.filter_by(
                installment_id=installment.id,
                event_type="due_today",
            ).first()
            if exists:
                continue
            active_count = PushSubscription.query.filter_by(
                organization_id=installment.contract.organization_id,
                is_active=True,
            ).count()
            if not active_count:
                continue

            sent = send_payload_to_org(app, installment.contract.organization_id, due_today_payload(installment))
            if sent:
                db.session.add(PushNotificationLog(
                    organization_id=installment.contract.organization_id,
                    installment_id=installment.id,
                    event_type="due_today",
                ))
                try:
                    db.session.commit()
                    sent_events += 1
                except IntegrityError:
                    db.session.rollback()
        for installment in candidates:
            fees_changed = _sync_installment_late_fee(installment, today_local) or fees_changed
            if installment.remaining <= Decimal("0.009"):
                continue
            reminder_log = PushNotificationLog.query.filter_by(
                installment_id=installment.id,
                event_type="overdue",
            ).first()
            is_repeat = reminder_log is not None
            if reminder_log and reminder_log.sent_at and (now_utc - reminder_log.sent_at) < repeat_after:
                continue
            active_count = PushSubscription.query.filter_by(
                organization_id=installment.contract.organization_id,
                is_active=True,
            ).count()
            if not active_count:
                continue

            sent = send_payload_to_org(
                app,
                installment.contract.organization_id,
                overdue_payload(installment, reminder=is_repeat),
            )
            if sent:
                if reminder_log is None:
                    reminder_log = PushNotificationLog(
                        organization_id=installment.contract.organization_id,
                        installment_id=installment.id,
                        event_type="overdue",
                    )
                    db.session.add(reminder_log)
                else:
                    # Keep one row per debt and move sent_at forward. This gives
                    # recurring reminders without growing the log table forever.
                    reminder_log.sent_at = now_utc
                try:
                    db.session.commit()
                    sent_events += 1
                except IntegrityError:
                    db.session.rollback()
        if fees_changed:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return sent_events


def start_push_scheduler(app):
    global _scheduler
    if _scheduler is not None or app.config.get("TESTING"):
        return
    if not app.config.get("PUSH_SCHEDULER_ENABLED", True):
        return
    if not _push_ready(app):
        app.logger.warning("Push scheduler desactivado: faltan claves VAPID o PUSH_NOTIFICATIONS_ENABLED=0")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        app.logger.warning("APScheduler no esta instalado; no se ejecutaran alertas automaticas.")
        return

    timezone_name = app.config.get("APP_TIMEZONE", "America/Santo_Domingo")
    interval = int(app.config.get("PUSH_CHECK_INTERVAL_MINUTES", 5))
    scheduler = BackgroundScheduler(timezone=timezone_name, daemon=True)
    scheduler.add_job(
        lambda: scan_overdue_and_notify(app),
        trigger="interval",
        minutes=interval,
        id="cuotago-payment-push",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(ZoneInfo(timezone_name)) + timedelta(seconds=12),
    )
    scheduler.start()
    _scheduler = scheduler
    atexit.register(lambda: scheduler.shutdown(wait=False) if scheduler.running else None)
    app.logger.info(
        "Push de cobros activo: revision cada %s minuto(s), recordatorio de atrasos cada %s hora(s) entre %s:00 y %s:00.",
        interval,
        app.config.get("PUSH_OVERDUE_REPEAT_HOURS", 2),
        app.config.get("PUSH_ALERT_START_HOUR", 8),
        app.config.get("PUSH_ALERT_END_HOUR", 22),
    )


@push_bp.get("/api/push/config")
@login_required
@permission_required("collections.view")
def push_config():
    return jsonify({
        "enabled": _push_ready(current_app),
        "publicKey": current_app.config.get("VAPID_PUBLIC_KEY", ""),
        "subscriptionCount": PushSubscription.query.filter_by(
            user_id=current_user.id,
            is_active=True,
        ).count(),
    })


@push_bp.post("/api/push/subscribe")
@login_required
@permission_required("collections.view")
def push_subscribe():
    if not _push_ready(current_app):
        return jsonify({"ok": False, "message": "Las notificaciones push no estan configuradas en el servidor."}), 503

    data = request.get_json(silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    keys = data.get("keys") or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()
    if not endpoint.startswith("https://") or not p256dh or not auth:
        return jsonify({"ok": False, "message": "Suscripcion push invalida."}), 400

    subscription = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if subscription is None:
        subscription = PushSubscription(endpoint=endpoint)
        db.session.add(subscription)

    subscription.organization_id = current_user.organization_id
    subscription.user_id = current_user.id
    subscription.p256dh = p256dh
    subscription.auth = auth
    subscription.user_agent = (request.headers.get("User-Agent") or "")[:300]
    subscription.is_active = True
    subscription.last_seen_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "message": "Alertas activadas en este telefono."})


@push_bp.post("/api/push/unsubscribe")
@login_required
@permission_required("collections.view")
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    if endpoint:
        PushSubscription.query.filter_by(
            endpoint=endpoint,
            user_id=current_user.id,
        ).update({"is_active": False})
        db.session.commit()
    return jsonify({"ok": True})


@push_bp.get("/api/push/pending-alerts")
@login_required
@permission_required("collections.view")
def push_pending_alerts():
    """Fallback visible mientras la app esta abierta si el navegador no logra crear Web Push."""
    tz = ZoneInfo(current_app.config.get("APP_TIMEZONE", "America/Santo_Domingo"))
    today_local = datetime.now(tz).date()
    candidates = (
        Installment.query.join(Contract)
        .filter(
            Contract.organization_id == current_user.organization_id,
            Contract.status == "active",
            Installment.due_date < today_local,
        )
        .order_by(Installment.due_date.asc())
        .limit(20)
        .all()
    )
    changed = False
    for item in candidates:
        changed = _sync_installment_late_fee(item, today_local) or changed
    if changed:
        db.session.commit()
    items = [overdue_payload(item) for item in candidates if item.remaining > Decimal("0.009")]
    return jsonify({"ok": True, "count": len(items), "items": items})


@push_bp.post("/api/push/test")
@login_required
@permission_required("collections.view")
def push_test():
    if not _push_ready(current_app):
        return jsonify({"ok": False, "message": "Push no esta configurado."}), 503

    tz = ZoneInfo(current_app.config.get("APP_TIMEZONE", "America/Santo_Domingo"))
    today_local = datetime.now(tz).date()
    overdue_candidates = (
        Installment.query.join(Contract)
        .filter(
            Contract.organization_id == current_user.organization_id,
            Contract.status == "active",
            Installment.due_date < today_local,
        )
        .order_by(Installment.due_date.asc(), Installment.id.asc())
        .limit(20)
        .all()
    )
    overdue_item = next((item for item in overdue_candidates if item.remaining > Decimal("0.009")), None)
    currency = getattr(current_user.organization, "currency", None) or "DOP"
    if overdue_item is not None:
        demo_client = overdue_item.contract.client.full_name
        demo_amount = _money(overdue_item.remaining, currency)
        demo_url = f"/contracts/{overdue_item.contract.id}#pay"
    else:
        demo_client = "Cliente de ejemplo"
        demo_amount = _money(Decimal("2500.00"), currency)
        demo_url = "/notifications"

    payload = {
        "type": "test",
        "title": "Pago atrasado",
        "body": f"Pago de {demo_client} atrasado · {demo_amount}",
        "url": demo_url,
        "tag": f"cuotago-test-{current_user.id}-{int(time.time() * 1000)}",
    }
    data = request.get_json(silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    query = PushSubscription.query.filter_by(user_id=current_user.id, is_active=True)
    if endpoint:
        query = query.filter_by(endpoint=endpoint)
    subscriptions = query.all()
    if not subscriptions:
        return jsonify({"ok": False, "sent": 0, "message": "Este telefono no tiene una suscripcion Push activa."}), 400

    sent = sum(1 for sub in subscriptions if send_payload_to_subscription(current_app, sub, payload))
    if sent:
        return jsonify({
            "ok": True,
            "sent": sent,
            "message": "Notificacion de prueba enviada a este telefono.",
            "preview": {"title": payload["title"], "body": payload["body"], "url": payload["url"]},
        })
    return jsonify({"ok": False, "sent": 0, "message": "El servicio Push no pudo entregar la prueba a este telefono."}), 502


@push_bp.post("/api/push/test-delayed")
@login_required
@permission_required("collections.view")
def push_test_delayed():
    """Schedule a real push so the installed PWA can be backgrounded before delivery."""
    if not _push_ready(current_app):
        return jsonify({"ok": False, "message": "Push no esta configurado en Railway."}), 503

    data = request.get_json(silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    delay = data.get("delay", 10)
    if not endpoint:
        return jsonify({"ok": False, "message": "No se encontro la suscripcion de este telefono."}), 400

    subscription = PushSubscription.query.filter_by(
        user_id=current_user.id, endpoint=endpoint, is_active=True
    ).first()
    if not subscription:
        return jsonify({"ok": False, "message": "Este telefono no tiene una suscripcion Push activa."}), 400

    seconds = _schedule_test_push(current_app._get_current_object(), subscription.id, delay)
    return jsonify({
        "ok": True,
        "delay": seconds,
        "message": f"Prueba programada. Sal de CuotaGo ahora; la alerta llegara en {seconds} segundos.",
    }), 202
