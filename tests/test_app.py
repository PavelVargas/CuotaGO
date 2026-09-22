from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
import os

import pytest

from cuotago import create_app
from cuotago.extensions import db
from cuotago.models import (
    AdminAuditLog, Asset, Client, CollectionNote, Contract, ContractScheduleChange, Expense, Installment,
    Organization, OrganizationSubscription, Payment, PaymentPromise, Purchase, PushNotificationLog,
    PushSubscription, SubscriptionPayment, SubscriptionPlan, Supplier, TenantAuditLog, User,
)


@pytest.fixture()
def app():
    test_db = os.getenv("TEST_DATABASE_URL")
    if not test_db:
        pytest.skip("Define TEST_DATABASE_URL con una base PostgreSQL exclusiva para pruebas.")
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": test_db,
        "SECRET_KEY": "test-key",
        "AUTO_CREATE_DB": False,
        "PUSH_SCHEDULER_ENABLED": False,
    })
    with app.app_context():
        if db.engine.dialect.name != "postgresql":
            pytest.fail("Las pruebas de CuotaGo requieren PostgreSQL.")
        db.drop_all()
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def register(client):
    return client.post(
        "/register",
        data={
            "business_name": "Préstamos Demo",
            "name": "Pavel",
            "email": "pavel@example.com",
            "password": "12345678",
            "confirm_password": "12345678",
        },
        follow_redirects=True,
    )


def test_register_login_and_dashboard(client, app):
    response = register(client)
    assert response.status_code == 200
    assert b"Acuerdos" in response.data
    with app.app_context():
        assert User.query.count() == 1
        assert OrganizationSubscription.query.count() == 1
        assert OrganizationSubscription.query.one().status == "pending"


def test_create_contract_and_register_payment(client, app):
    register(client)
    client.post(
        "/clients/new",
        data={"full_name": "Juan Perez", "phone": "8095551234"},
        follow_redirects=True,
    )
    client.post(
        "/assets/new",
        data={
            "kind": "phone",
            "name": "iPhone 15",
            "brand": "Apple",
            "model": "15",
            "identifier": "IMEI-001",
            "estimated_value": "60000",
        },
        follow_redirects=True,
    )

    with app.app_context():
        person = Client.query.first()
        asset = Asset.query.first()
        person_id = person.id
        asset_id = asset.id

    start = date.today()
    response = client.post(
        "/contracts/new",
        data={
            "client_id": person_id,
            "asset_id": asset_id,
            "deal_type": "credit_sale",
            "total_amount": "60000",
            "down_payment": "10000",
            "installment_amount": "10000",
            "frequency": "monthly",
            "start_date": start.isoformat(),
            "first_due_date": (start + timedelta(days=30)).isoformat(),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Saldo pendiente" in response.data

    with app.app_context():
        contract = Contract.query.first()
        assert contract is not None
        assert contract.balance == Decimal("50000.00")
        assert Installment.query.count() == 5
        contract_id = contract.id
        assert Asset.query.first().status == "on_loan"

    response = client.post(
        f"/contracts/{contract_id}/pay",
        data={"amount": "10000", "method": "cash", "note": "Primer pago"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Pago de" in response.data

    with app.app_context():
        contract = db.session.get(Contract, contract_id)
        assert contract.balance == Decimal("40000.00")
        assert contract.installments[0].is_paid


def test_asset_photo_upload_and_private_delivery(client, app):
    register(client)
    tiny_png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    )
    response = client.post(
        "/assets/new",
        data={
            "kind": "phone",
            "name": "Telefono con foto",
            "quantity_total": "2",
            "estimated_value": "12000",
            "image": (BytesIO(tiny_png), "producto.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        asset = Asset.query.filter_by(name="Telefono con foto").one()
        asset_id = asset.id
        assert asset.image_mime == "image/png"

    image = client.get(f"/assets/{asset_id}/image")
    assert image.status_code == 200
    assert image.mimetype == "image/png"
    assert image.data.startswith(b"\x89PNG")
    assert image.headers["Cache-Control"] == "private, no-store"


def test_quick_contract_creates_client_and_asset_inline(client, app):
    register(client)
    start = date.today()
    response = client.post(
        "/contracts/new",
        data={
            "client_name": "Maria Lopez",
            "client_phone": "8095559999",
            "asset_name": "Samsung S25",
            "asset_kind": "phone",
            "asset_identifier": "IMEI-QUICK-001",
            "deal_type": "credit_sale",
            "total_amount": "48000",
            "down_payment": "8000",
            "installment_amount": "5000",
            "frequency": "biweekly",
            "start_date": start.isoformat(),
            "first_due_date": (start + timedelta(days=14)).isoformat(),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Saldo pendiente" in response.data

    with app.app_context():
        person = Client.query.filter_by(full_name="Maria Lopez").one()
        asset = Asset.query.filter_by(name="Samsung S25").one()
        contract = Contract.query.one()
        assert person.phone == "8095559999"
        assert asset.identifier == "IMEI-QUICK-001"
        assert asset.status == "on_loan"
        assert contract.balance == Decimal("40000.00")
        assert Installment.query.count() == 8


def test_push_subscription_can_be_saved(client, app):
    register(client)
    response = client.post(
        "/api/push/subscribe",
        json={
            "endpoint": "https://push.example.test/subscription-1",
            "keys": {"p256dh": "test-p256dh", "auth": "test-auth"},
        },
    )
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    with app.app_context():
        subscription = PushSubscription.query.one()
        assert subscription.is_active is True
        assert subscription.endpoint.endswith("subscription-1")


def test_payment_notification_center_works_without_web_push(client, app):
    register(client)
    start = date.today() - timedelta(days=20)
    due = date.today() - timedelta(days=5)
    response = client.post(
        "/contracts/new",
        data={
            "client_name": "Cliente Atrasado",
            "client_phone": "8095550101",
            "asset_name": "iPhone de prueba",
            "asset_kind": "phone",
            "asset_identifier": "DEMO-ALERTA-001",
            "deal_type": "credit_sale",
            "total_amount": "30000",
            "down_payment": "5000",
            "installment_amount": "5000",
            "frequency": "monthly",
            "start_date": start.isoformat(),
            "first_due_date": due.isoformat(),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    center = client.get("/notifications")
    assert center.status_code == 200
    assert b"Cliente Atrasado" in center.data
    assert b"Pago atrasado" in center.data

    api = client.get("/api/notifications")
    payload = api.get_json()
    assert api.status_code == 200
    assert payload["urgentCount"] >= 1
    assert payload["items"][0]["url"].endswith("#pay")


def test_mobile_bottom_bar_removed_and_museomoderno_loaded(client):
    response = register(client)
    assert b"mobile-tabbar" not in response.data
    assert b"MuseoModerno" in response.data


def test_auth_pages_force_light_theme(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert b'data-auth-screen="1"' in response.data
    assert b'auth-theme-toggle' not in response.data


def test_resume_screen_shows_remembered_account(client, app):
    register(client)
    response = client.get('/resume')
    assert response.status_code == 200
    assert b'Continua con la cuenta' in response.data or b'Contin\xc3\xbaa con la cuenta' in response.data
    assert b'pavel@example.com' in response.data
    assert b'>Entrar<' in response.data


def test_superadmin_can_clear_company_data(client, app):
    register(client)
    with app.app_context():
        owner = User.query.filter_by(email='pavel@example.com').one()
        admin_org = Organization(name='Admin CuotaGo', currency='DOP')
        admin = User(organization=admin_org, name='Admin', email='admin@example.com', role='superadmin')
        admin.set_password('superadmin12345')
        db.session.add_all([admin_org, admin])
        db.session.commit()

    client.post('/logout')
    client.post('/login', data={'email': 'admin@example.com', 'password': 'superadmin12345'}, follow_redirects=True)
    with app.app_context():
        target_org = User.query.filter_by(email='pavel@example.com').one().organization_id

    response = client.post(
        f'/superadmin/organizations/{target_org}/reset',
        data={'confirm_phrase': 'VACIAR Préstamos Demo'},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'quedo vacia' in response.data or b'qued\xc3\xb3 vac\xc3\xada' in response.data
    with app.app_context():
        assert User.query.filter_by(email='pavel@example.com').count() == 1
        assert Client.query.filter_by(organization_id=target_org).count() == 0
        assert Asset.query.filter_by(organization_id=target_org).count() == 0
        assert Contract.query.filter_by(organization_id=target_org).count() == 0


def test_superadmin_sensitive_actions_require_real_action_phrase(client, app):
    register(client)
    with app.app_context():
        target = User.query.filter_by(email='pavel@example.com').one().organization
        target_id = target.id
        original_clients = Client.query.filter_by(organization_id=target_id).count()
        admin_org = Organization(name='Admin Seguridad', currency='DOP')
        admin = User(organization=admin_org, name='Admin', email='security-admin@example.com', role='superadmin')
        admin.set_password('superadmin12345')
        db.session.add_all([admin_org, admin])
        db.session.commit()

    client.post('/logout')
    client.post('/login', data={'email': 'security-admin@example.com', 'password': 'superadmin12345'}, follow_redirects=True)

    wrong = client.post(
        f'/superadmin/organizations/{target_id}/reset',
        data={'confirm_phrase': 'Préstamos Demo'},
        follow_redirects=True,
    )
    assert wrong.status_code == 200
    assert b'Frase incorrecta' in wrong.data
    with app.app_context():
        assert Client.query.filter_by(organization_id=target_id).count() == original_clients

    correct = client.post(
        f'/superadmin/organizations/{target_id}/reset',
        data={'confirm_phrase': 'VACIAR Préstamos Demo'},
        follow_redirects=True,
    )
    assert correct.status_code == 200
    with app.app_context():
        assert Client.query.filter_by(organization_id=target_id).count() == 0


def test_superadmin_delete_company_requires_keyword_and_really_deletes(client, app):
    register(client)
    with app.app_context():
        target = User.query.filter_by(email='pavel@example.com').one().organization
        target_id = target.id
        admin_org = Organization(name='Admin Borrado', currency='DOP')
        admin = User(organization=admin_org, name='Admin', email='delete-admin@example.com', role='superadmin')
        admin.set_password('superadmin12345')
        db.session.add_all([admin_org, admin])
        db.session.commit()

    client.post('/logout')
    client.post('/login', data={'email': 'delete-admin@example.com', 'password': 'superadmin12345'}, follow_redirects=True)

    blocked = client.post(
        f'/superadmin/organizations/{target_id}/delete',
        data={'confirm_phrase': 'ELIMINAR OTRA EMPRESA', 'confirm_delete': 'yes'},
        follow_redirects=True,
    )
    assert blocked.status_code == 200
    with app.app_context():
        assert db.session.get(Organization, target_id) is not None

    deleted = client.post(
        f'/superadmin/organizations/{target_id}/delete',
        data={'confirm_phrase': 'ELIMINAR Préstamos Demo', 'confirm_delete': 'yes'},
        follow_redirects=True,
    )
    assert deleted.status_code == 200
    with app.app_context():
        assert db.session.get(Organization, target_id) is None
        assert User.query.filter_by(organization_id=target_id).count() == 0
        assert OrganizationSubscription.query.filter_by(organization_id=target_id).count() == 0
        assert AdminAuditLog.query.filter_by(organization_id=target_id, action='organization.delete').count() == 1


def test_superadmin_manages_plans_subscription_payment_and_audit(client, app):
    register(client)
    with app.app_context():
        target = User.query.filter_by(email='pavel@example.com').one().organization
        target_id = target.id
        admin_org = Organization(name='Admin CuotaGo', currency='DOP')
        admin = User(organization=admin_org, name='Admin', email='admin2@example.com', role='superadmin', is_enabled=True)
        admin.set_password('superadmin12345')
        db.session.add_all([admin_org, admin])
        db.session.commit()

    client.post('/logout')
    client.post('/login', data={'email': 'admin2@example.com', 'password': 'superadmin12345'}, follow_redirects=True)
    create_plan = client.post('/superadmin/plans', data={
        'name': 'Mensual', 'price': '3000', 'currency': 'DOP', 'billing_interval_months': '1'
    }, follow_redirects=True)
    assert create_plan.status_code == 200
    with app.app_context():
        plan = SubscriptionPlan.query.filter_by(name='Mensual').one()
        plan_id = plan.id

    update = client.post(f'/superadmin/organizations/{target_id}/subscription', data={
        'plan_id': str(plan_id), 'status': 'active', 'amount_override': '',
        'current_period_start': date.today().isoformat(),
        'current_period_end': (date.today() + timedelta(days=29)).isoformat(),
        'grace_ends_at': '', 'notes': 'Cliente mensual',
    }, follow_redirects=True)
    assert update.status_code == 200

    payment = client.post(f'/superadmin/organizations/{target_id}/subscription/payment', data={
        'amount': '3000', 'months': '1', 'method': 'transfer', 'reference': 'TEST-001'
    }, follow_redirects=True)
    assert payment.status_code == 200
    with app.app_context():
        subscription = OrganizationSubscription.query.filter_by(organization_id=target_id).one()
        assert subscription.plan_id == plan_id
        assert subscription.status == 'active'
        subscription_payment = SubscriptionPayment.query.filter_by(subscription_id=subscription.id).one()
        payment_id = subscription_payment.id
        assert AdminAuditLog.query.filter_by(organization_id=target_id).count() >= 2

    voided = client.post(
        f'/superadmin/organizations/{target_id}/subscription/payments/{payment_id}/void',
        data={'reason': 'Pago registrado por error'},
        follow_redirects=True,
    )
    assert voided.status_code == 200
    with app.app_context():
        subscription_payment = db.session.get(SubscriptionPayment, payment_id)
        assert subscription_payment.voided_at is not None
        assert subscription_payment.void_reason == 'Pago registrado por error'


def test_suspended_subscription_blocks_company_but_not_logout(client, app):
    register(client)
    with app.app_context():
        subscription = OrganizationSubscription.query.one()
        subscription.status = 'suspended'
        db.session.commit()

    response = client.get('/contracts', follow_redirects=True)
    assert response.status_code == 200
    assert b'Estado de suscripci' in response.data or b'Suspendida' in response.data
    logout = client.post('/logout', follow_redirects=False)
    assert logout.status_code in {302, 303}


def test_superadmin_dashboard_has_professional_admin_sections():
    from pathlib import Path
    html = Path('cuotago/templates/admin/index.html').read_text(encoding='utf-8')
    organization = Path('cuotago/templates/admin/organization.html').read_text(encoding='utf-8')
    assert 'MRR estimado' in html
    assert 'Centro de administración' in html
    assert 'Pago de suscripción' in organization
    assert 'Historial de pagos' in organization
    assert 'Zona sensible' in organization
    assert 'confirm_phrase' in organization
    assert 'data-admin-panel-target' in organization
    assert 'LIMPIAR {{ organization.name }}' in organization
    assert 'VACIAR {{ organization.name }}' in organization
    assert 'ELIMINAR {{ organization.name }}' in organization



def test_delayed_push_route_exists_in_source():
    from pathlib import Path
    source = Path('cuotago/push.py').read_text(encoding='utf-8')
    assert '/api/push/test-delayed' in source
    js = Path('cuotago/static/js/app.js').read_text(encoding='utf-8')
    assert 'data-push-test-background' in js
    assert 'setupPullToRefresh' in js


def test_calendar_lists_new_agreement_dates(client, app):
    register(client)
    start = date.today()
    due = start + timedelta(days=90)
    response = client.post(
        "/contracts/new",
        data={
            "client_name": "Cliente Calendario",
            "asset_name": "Equipo Calendario",
            "asset_kind": "phone",
            "asset_stock_quantity": "2",
            "quantity": "1",
            "deal_type": "credit_sale",
            "total_amount": "20000",
            "down_payment": "0",
            "installment_amount": "5000",
            "frequency": "monthly",
            "start_date": start.isoformat(),
            "first_due_date": due.isoformat(),
            "daily_late_interest": "0",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    calendar = client.get('/calendar')
    assert calendar.status_code == 200
    assert b'Cliente Calendario' in calendar.data
    assert due.strftime('%d/%m/%Y').encode() in calendar.data
    assert b'data-calendar-search' in calendar.data
    assert b'data-calendar-grid' in calendar.data
    assert b'paymentCalendarEvents' in calendar.data


def test_calendar_frontend_has_realtime_client_filter_and_payment_day_state():
    from pathlib import Path
    js = Path('cuotago/static/js/app.js').read_text(encoding='utf-8')
    css = Path('cuotago/static/css/app.css').read_text(encoding='utf-8')
    assert 'setupPaymentCalendar' in js
    assert "searchInput?.addEventListener('input'" in js
    assert 'has-payment' in js
    assert '.real-calendar-day.has-payment' in css
    assert 'var(--primary)' in css


def test_inventory_quantity_allows_multiple_agreements(client, app):
    register(client)
    client.post('/assets/new', data={
        'kind': 'phone', 'name': 'iPhone 15 Pro Max', 'quantity_total': '3', 'estimated_value': '60000'
    }, follow_redirects=True)
    with app.app_context():
        asset_id = Asset.query.filter_by(name='iPhone 15 Pro Max').one().id

    start = date.today()
    for idx, person in enumerate(['Hermano', 'Tia'], start=1):
        response = client.post('/contracts/new', data={
            'client_name': person,
            'asset_id': asset_id,
            'quantity': '1',
            'deal_type': 'credit_sale',
            'total_amount': '60000',
            'down_payment': '10000',
            'installment_amount': '10000',
            'frequency': 'monthly',
            'start_date': start.isoformat(),
            'first_due_date': (start + timedelta(days=30)).isoformat(),
            'daily_late_interest': '0',
        }, follow_redirects=True)
        assert response.status_code == 200

    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        assert asset.quantity_total == 3
        assert asset.committed_quantity == 2
        assert asset.available_quantity == 1
        assert asset.status == 'available'

    response = client.post('/contracts/new', data={
        'client_name': 'Cliente sin stock',
        'asset_id': asset_id,
        'quantity': '2',
        'deal_type': 'credit_sale',
        'total_amount': '120000',
        'down_payment': '0',
        'installment_amount': '10000',
        'frequency': 'monthly',
        'start_date': start.isoformat(),
        'first_due_date': (start + timedelta(days=30)).isoformat(),
        'daily_late_interest': '0',
    }, follow_redirects=True)
    assert b'Solo quedan 1 unidad' in response.data


def test_daily_late_interest_is_added_and_paid(client, app):
    register(client)
    start = date.today() - timedelta(days=10)
    due = date.today() - timedelta(days=3)
    response = client.post('/contracts/new', data={
        'client_name': 'Cliente Interes',
        'asset_name': 'Telefono con interes',
        'asset_kind': 'phone',
        'asset_stock_quantity': '1',
        'quantity': '1',
        'deal_type': 'credit_sale',
        'total_amount': '10000',
        'down_payment': '0',
        'installment_amount': '5000',
        'frequency': 'monthly',
        'start_date': start.isoformat(),
        'first_due_date': due.isoformat(),
        'daily_late_interest': '100',
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        contract = Contract.query.filter_by().one()
        contract_id = contract.id

    detail = client.get(f'/contracts/{contract_id}')
    assert detail.status_code == 200
    with app.app_context():
        contract = db.session.get(Contract, contract_id)
        first = contract.installments[0]
        assert first.late_fee_amount == Decimal('300.00')
        assert contract.balance == Decimal('10300.00')

    client.post(f'/contracts/{contract_id}/pay', data={
        'amount': '300', 'method': 'cash'
    }, follow_redirects=True)
    with app.app_context():
        contract = db.session.get(Contract, contract_id)
        first = contract.installments[0]
        assert first.late_fee_paid == Decimal('300.00')
        assert first.paid_amount == Decimal('0.00')
        assert contract.payments[0].late_fee_amount == Decimal('300.00')


def test_dashboard_has_single_agreements_entry(client):
    response = register(client)
    html = response.data.decode('utf-8')
    assert 'Nuevo acuerdo</strong>' not in html
    assert html.count('>Acuerdos</strong>') == 1


def test_installment_count_uses_inventory_price_and_exact_schedule(client, app):
    register(client)
    client.post('/assets/new', data={
        'kind': 'phone', 'name': 'iPhone Plan', 'quantity_total': '2', 'estimated_value': '60000'
    }, follow_redirects=True)
    with app.app_context():
        asset_id = Asset.query.filter_by(name='iPhone Plan').one().id

    start = date.today()
    response = client.post('/contracts/new', data={
        'client_name': 'Cliente Cuotas',
        'asset_id': asset_id,
        'quantity': '1',
        'deal_type': 'credit_sale',
        'down_payment': '10000',
        'installment_count': '5',
        'frequency': 'monthly',
        'start_date': start.isoformat(),
        'first_due_date': (start + timedelta(days=30)).isoformat(),
        'daily_late_interest': '0',
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        contract = Contract.query.one()
        assert contract.total_amount == Decimal('60000.00')
        assert contract.installment_amount == Decimal('10000.00')
        assert len(contract.installments) == 5
        assert sum((item.amount for item in contract.installments), Decimal('0.00')) == Decimal('50000.00')


def test_launcher_v3_is_four_by_two_without_outer_module_cards():
    from pathlib import Path
    css = Path('cuotago/static/css/app.css').read_text(encoding='utf-8')
    html = Path('cuotago/templates/dashboard.html').read_text(encoding='utf-8')
    assert 'dashboard-launcher-v3' in html
    assert '.dashboard-launcher-v3 .module-grid' in css
    assert 'grid-template-columns:repeat(4,minmax(0,1fr))' in css
    assert '.dashboard-launcher-v3 .module-card::after{display:none!important}' in css
    assert html.index('class="module-grid"') < html.index('class="home-status"')


def test_remembered_authenticated_session_can_open_modules_without_resume_redirect(client):
    register(client)
    with client.session_transaction() as session:
        session['_fresh'] = False

    for path in ['/contracts', '/collections', '/notifications', '/clients', '/purchases', '/assets', '/calendar', '/reports', '/documents', '/settings']:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, f"{path} redirected unexpectedly to {response.headers.get('Location')}"



def test_agreement_profit_margin_and_advance_controls_are_present():
    from pathlib import Path
    form_html = Path('cuotago/templates/contracts/form.html').read_text(encoding='utf-8')
    detail_html = Path('cuotago/templates/contracts/detail.html').read_text(encoding='utf-8')
    app_js = Path('cuotago/static/js/app.js').read_text(encoding='utf-8')
    assert 'name="profit_margin_percent"' in form_html
    assert 'id="profitAmountPreview"' in form_html
    assert 'data-payment-kind="advance"' in detail_html
    assert '>Abonar</span>' in detail_html
    assert "REGISTRAR ABONO" in app_js


def test_profit_margin_is_applied_before_installments(client, app):
    register(client)
    client.post('/assets/new', data={
        'kind': 'phone', 'name': 'iPhone 15 Margen', 'quantity_total': '1', 'estimated_value': '50000'
    }, follow_redirects=True)
    with app.app_context():
        asset_id = Asset.query.filter_by(name='iPhone 15 Margen').one().id

    start = date.today()
    response = client.post('/contracts/new', data={
        'client_name': 'Cliente Margen',
        'asset_id': asset_id,
        'quantity': '1',
        'deal_type': 'credit_sale',
        'profit_margin_percent': '20',
        'down_payment': '0',
        'installment_count': '6',
        'frequency': 'monthly',
        'start_date': start.isoformat(),
        'first_due_date': (start + timedelta(days=30)).isoformat(),
        'daily_late_interest': '0',
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        contract = Contract.query.one()
        assert contract.base_amount == Decimal('50000.00')
        assert contract.profit_margin_percent == Decimal('20.00')
        assert contract.profit_amount == Decimal('10000.00')
        assert contract.total_amount == Decimal('60000.00')
        assert contract.installment_amount == Decimal('10000.00')
        assert len(contract.installments) == 6


def test_settings_demo_enables_real_background_push_and_dashboard_desktop_icons_are_larger():
    from pathlib import Path
    js = Path('cuotago/static/js/app.js').read_text(encoding='utf-8')
    css = Path('cuotago/static/css/app.css').read_text(encoding='utf-8')
    settings = Path('cuotago/templates/settings/index.html').read_text(encoding='utf-8')
    push = Path('cuotago/push.py').read_text(encoding='utf-8')
    assert 'data-notification-demo' in settings
    assert 'subscribePushFromUserGesture' in js
    assert "'/api/push/test-delayed'" in js
    assert 'def due_today_payload' in push
    assert 'event_type="due_today"' in push
    assert 'width:104px' in css
    assert 'width:84px;height:84px' in css


def test_mora_can_be_enabled_later_without_backcharging(client, app):
    register(client)
    start = date.today() - timedelta(days=20)
    due = date.today() - timedelta(days=7)
    response = client.post('/contracts/new', data={
        'client_name': 'Cliente Sin Mora',
        'asset_name': 'Equipo Sin Mora',
        'asset_kind': 'phone',
        'asset_stock_quantity': '1',
        'quantity': '1',
        'deal_type': 'credit_sale',
        'total_amount': '10000',
        'down_payment': '0',
        'installment_amount': '5000',
        'frequency': 'monthly',
        'start_date': start.isoformat(),
        'first_due_date': due.isoformat(),
        'daily_late_interest': '0',
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        contract = Contract.query.one()
        contract_id = contract.id
        assert contract.late_fee_started_on is None
        assert contract.installments[0].late_fee_amount == Decimal('0.00')

    response = client.post(
        f'/contracts/{contract_id}/late-fee',
        data={'daily_late_interest': '100'},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        contract = db.session.get(Contract, contract_id)
        first = contract.installments[0]
        assert contract.daily_late_interest == Decimal('100.00')
        assert contract.late_fee_started_on == date.today()
        # The installment was already seven days late, but mora starts today.
        assert first.late_fee_amount == Decimal('0.00')
        contract.late_fee_started_on = date.today() - timedelta(days=2)
        db.session.commit()

    detail = client.get(f'/contracts/{contract_id}')
    assert detail.status_code == 200
    with app.app_context():
        first = db.session.get(Contract, contract_id).installments[0]
        assert first.late_fee_amount == Decimal('200.00')


def test_contract_can_be_deleted_and_inventory_is_released(client, app):
    register(client)
    client.post('/assets/new', data={
        'kind': 'phone', 'name': 'iPhone Reutilizable', 'quantity_total': '1', 'estimated_value': '50000'
    }, follow_redirects=True)
    with app.app_context():
        asset_id = Asset.query.filter_by(name='iPhone Reutilizable').one().id

    start = date.today()
    client.post('/contracts/new', data={
        'client_name': 'Cliente Rehacer',
        'asset_id': asset_id,
        'quantity': '1',
        'deal_type': 'credit_sale',
        'total_amount': '50000',
        'down_payment': '0',
        'installment_amount': '10000',
        'frequency': 'monthly',
        'start_date': start.isoformat(),
        'first_due_date': (start + timedelta(days=30)).isoformat(),
        'daily_late_interest': '0',
    }, follow_redirects=True)

    with app.app_context():
        contract = Contract.query.one()
        contract_id = contract.id
        installment_id = contract.installments[0].id
        org_id = contract.organization_id
        db.session.add(PushNotificationLog(
            organization_id=org_id, installment_id=installment_id, event_type='overdue'
        ))
        db.session.commit()
        assert db.session.get(Asset, asset_id).available_quantity == 0

    response = client.post(f'/contracts/{contract_id}/delete', follow_redirects=True)
    assert response.status_code == 200
    assert b'Acuerdo eliminado' in response.data
    with app.app_context():
        assert Contract.query.count() == 0
        assert Installment.query.count() == 0
        assert PushNotificationLog.query.count() == 0
        asset = db.session.get(Asset, asset_id)
        assert asset.available_quantity == 1
        assert asset.status == 'available'


def test_purchase_registers_cost_supplier_and_stock_without_changing_sale_price(client, app):
    register(client)
    response = client.post(
        '/purchases/new',
        data={
            'asset_name': 'iPhone Compra',
            'asset_kind': 'phone',
            'quantity': '3',
            'unit_cost': '40000',
            'purchase_date': date.today().isoformat(),
            'supplier': 'Proveedor Demo',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Orden de compra registrada' in response.data
    with app.app_context():
        asset = Asset.query.filter_by(name='iPhone Compra').one()
        purchase = Purchase.query.one()
        supplier = Supplier.query.one()
        assert asset.quantity_total == 3
        assert asset.estimated_value == Decimal('40000.00')
        assert asset.sale_price == Decimal('0.00')
        assert supplier.name == 'Proveedor Demo'
        assert purchase.supplier_id == supplier.id
        assert purchase.total_cost == Decimal('120000.00')
        assert purchase.expected_profit == Decimal('0.00')


def test_purchase_existing_asset_uses_weighted_cost_and_adds_stock(client, app):
    register(client)
    client.post('/assets/new', data={'kind':'phone','name':'Stock base','quantity_total':'2','estimated_value':'100','sale_price':'150'}, follow_redirects=True)
    with app.app_context():
        asset_id = Asset.query.filter_by(name='Stock base').one().id
    response = client.post('/purchases/new', data={'asset_id':asset_id,'quantity':'2','unit_cost':'200','purchase_date':date.today().isoformat(),'supplier':'Proveedor Stock'}, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        asset = db.session.get(Asset, asset_id)
        assert asset.quantity_total == 4
        assert asset.estimated_value == Decimal('150.00')
        assert asset.sale_price == Decimal('150.00')


def test_purchase_form_exposes_inventory_selector_and_inline_supplier_creation():
    from pathlib import Path
    template = Path('cuotago/templates/purchases/form.html').read_text(encoding='utf-8')
    assert 'Seleccionar del inventario...' in template
    assert '+ Crear artículo nuevo' in template
    assert '+ Crear proveedor nuevo' in template
    assert 'item_unit_sale_price' not in template


def test_reports_v19_has_two_column_mobile_kpis_and_core_business_sections():
    from pathlib import Path
    template = Path('cuotago/templates/reports/index.html').read_text(encoding='utf-8')
    css = Path('cuotago/static/css/app.css').read_text(encoding='utf-8')
    main = Path('cuotago/main.py').read_text(encoding='utf-8')

    assert 'report-kpi-grid-v19' in template
    assert 'Margen de ganancia' in template
    assert 'Ganancia esperada' in template
    assert 'Capital recuperado' in template
    assert 'MORA' in template
    assert 'INVENTARIO' in template
    assert 'Actividad reciente' in template
    assert '.report-kpi-grid-v19{grid-template-columns:repeat(2,minmax(0,1fr))' in css
    assert 'profit_realized' in main
    assert 'late_fee_generated' in main
    assert 'inventory_available_value' in main
    assert 'recent_activity' in main

def test_reminders_v20_compacts_dashboard_and_adds_dedicated_view():
    from pathlib import Path
    dashboard = Path('cuotago/templates/dashboard.html').read_text(encoding='utf-8')
    reminders = Path('cuotago/templates/reminders/index.html').read_text(encoding='utf-8')
    css = Path('cuotago/static/css/app.css').read_text(encoding='utf-8')
    main = Path('cuotago/main.py').read_text(encoding='utf-8')
    base = Path('cuotago/templates/base.html').read_text(encoding='utf-8')
    sw = Path('cuotago/static/service-worker.js').read_text(encoding='utf-8')

    assert 'home-reminder-button' in dashboard
    assert 'Lo que necesita atención' not in dashboard
    assert "url_for('main.reminders')" in dashboard
    assert 'reminder_count' in dashboard
    assert '@main_bp.get("/reminders")' in main
    assert 'reminders/index.html' in main
    assert 'PRÓXIMOS 7 DÍAS' in reminders
    assert 'reminder-v20-row' in reminders
    assert '.home-reminder-button{' in css
    assert '.reminders-page-v20{' in css
    assert '-ui-v33' in base
    assert "1.15.0-ui-v33" in sw



def test_overdue_push_repeats_outside_app_without_notification_pileup():
    from pathlib import Path
    push = Path('cuotago/push.py').read_text(encoding='utf-8')
    config = Path('config.py').read_text(encoding='utf-8')
    worker = Path('cuotago/static/service-worker.js').read_text(encoding='utf-8')
    assert 'PUSH_OVERDUE_REPEAT_HOURS' in config
    assert 'PUSH_ALERT_END_HOUR' in config
    assert 'repeat_after = timedelta(hours=repeat_hours)' in push
    assert 'reminder_log.sent_at = now_utc' in push
    assert 'Recordatorio de cobro' in push
    assert 'replaceKey' in push
    assert 'getNotifications()' in worker
    assert "1.15.0-ui-v33" in worker


def test_purchase_batch_registers_multiple_items_in_one_submit(client, app):
    register(client)
    client.post('/assets/new', data={
        'kind': 'phone', 'name': 'Producto existente lote', 'quantity_total': '2',
        'estimated_value': '100', 'sale_price': '150'
    }, follow_redirects=True)
    with app.app_context():
        existing_id = Asset.query.filter_by(name='Producto existente lote').one().id

    response = client.post('/purchases/new', data={
        'purchase_date': date.today().isoformat(),
        'supplier': 'Proveedor lote',
        'reference': 'FAC-001',
        'item_mode': ['existing', 'new'],
        'item_asset_id': [str(existing_id), ''],
        'item_name': ['', 'Toyota Corolla lote'],
        'item_kind': ['other', 'car'],
        'item_quantity': ['3', '2'],
        'item_unit_cost': ['200', '500000'],
        'item_notes': ['Reposicion', 'Dos unidades'],
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'2 art' in response.data

    with app.app_context():
        purchases = Purchase.query.order_by(Purchase.id.asc()).all()
        assert len(purchases) == 2
        assert sum(p.quantity for p in purchases) == 5
        existing = db.session.get(Asset, existing_id)
        assert existing.quantity_total == 5
        assert existing.estimated_value == Decimal('160.00')
        assert existing.sale_price == Decimal('150.00')
        new_asset = Asset.query.filter_by(name='Toyota Corolla lote').one()
        assert new_asset.quantity_total == 2
        assert new_asset.estimated_value == Decimal('500000.00')
        assert new_asset.sale_price == Decimal('0.00')
        assert all(p.supplier == 'Proveedor lote' for p in purchases)
        assert all(p.reference == 'FAC-001' for p in purchases)
        assert len({p.batch_key for p in purchases}) == 1
        assert all(p.supplier_id for p in purchases)


def test_purchase_form_supports_dynamic_multiple_rows_and_launcher_flows_left_to_right():
    from pathlib import Path
    form_html = Path('cuotago/templates/purchases/form.html').read_text(encoding='utf-8')
    css = Path('cuotago/static/css/app.css').read_text(encoding='utf-8')
    assert 'data-add-purchase-item' in form_html
    assert 'name="item_quantity"' in form_html
    assert 'name="item_unit_cost"' in form_html
    assert 'name="item_unit_sale_price"' not in form_html
    assert 'Seleccionar del inventario...' in form_html
    assert '+ Crear proveedor nuevo' in form_html
    assert 'Guardar orden · ${all.length} artículos' in form_html
    assert '.dashboard-launcher-v3 .module-grid>.module-card:last-child{grid-column:2 / span 2}' not in css
    assert 'grid-column:auto!important' in css



def test_documents_module_uses_shared_catalog_and_renders_live_guide(client):
    from pathlib import Path
    register(client)
    response = client.get('/documents')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert 'Guía de uso de CuotaGo' in html
    assert 'Manual de uso' in html
    assert 'actualizado automáticamente' in html
    assert 'Buscar: compras, mora, inventario, cobros...' in html
    assert 'Compras solo modifica el costo de compra' in html
    assert 'No necesitas abrir ni cerrar una caja para cobrar.' in html
    assert 'Documentos' in html

    dashboard = Path('cuotago/templates/dashboard.html').read_text(encoding='utf-8')
    main = Path('cuotago/main.py').read_text(encoding='utf-8')
    catalog = Path('cuotago/module_catalog.py').read_text(encoding='utf-8')
    assert '{% for module in modules %}' in dashboard
    assert 'module_catalog()' in main
    assert '"slug": "documents"' in catalog
    assert '"endpoint": "main.documents"' in catalog


def test_documents_module_is_present_in_launcher(client):
    response = register(client)
    html = response.data.decode('utf-8')
    assert html.count('>Documentos</strong>') == 1
    assert '/documents' in html


def test_v115_collections_history_promises_receipts_and_expenses_are_wired():
    from pathlib import Path
    main = Path('cuotago/main.py').read_text(encoding='utf-8')
    models = Path('cuotago/models.py').read_text(encoding='utf-8')
    catalog = Path('cuotago/module_catalog.py').read_text(encoding='utf-8')
    client_detail = Path('cuotago/templates/clients/detail.html').read_text(encoding='utf-8')
    contract_detail = Path('cuotago/templates/contracts/detail.html').read_text(encoding='utf-8')
    reports = Path('cuotago/templates/reports/index.html').read_text(encoding='utf-8')

    assert 'class PaymentPromise' in models
    assert 'class CollectionNote' in models
    assert 'class ContractScheduleChange' in models
    assert 'class Expense' in models
    assert 'class TenantAuditLog' in models
    assert '@main_bp.post("/contracts/<int:contract_id>/reschedule")' in main
    assert '@main_bp.get("/payments/<int:payment_id>/receipt")' in main
    assert '@main_bp.get("/clients/<int:client_id>/statement")' in main
    assert '@main_bp.route("/expenses", methods=["GET", "POST"])' in main
    assert 'Promesas de pago' in client_detail
    assert 'Notas de cobranza' in client_detail
    assert 'Reprogramar cuotas' in contract_detail
    assert 'Entradas y salidas reales' in reports
    assert '"slug": "expenses"' in catalog


def test_payment_can_fulfill_promise_and_generates_receipt(client, app):
    register(client)
    start = date.today()
    response = client.post('/contracts/new', data={
        'client_name': 'Cliente Promesa', 'client_phone': '8095550909',
        'asset_name': 'Equipo Promesa', 'asset_kind': 'phone',
        'deal_type': 'credit_sale', 'total_amount': '10000', 'down_payment': '0',
        'installment_count': '2', 'installment_amount': '5000', 'frequency': 'monthly',
        'start_date': start.isoformat(), 'first_due_date': start.isoformat(),
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        person = Client.query.filter_by(full_name='Cliente Promesa').one()
        contract = Contract.query.one()
        person_id, contract_id = person.id, contract.id

    response = client.post(f'/clients/{person_id}/promises', data={
        'promised_date': start.isoformat(), 'amount': '5000', 'contract_id': str(contract_id), 'note': 'Paga hoy'
    }, follow_redirects=True)
    assert response.status_code == 200

    response = client.post(f'/contracts/{contract_id}/pay', data={
        'amount': '5000', 'method': 'transfer', 'reference': 'TRX-001', 'payment_kind': 'payment', 'show_receipt': '1'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Recibo de pago' in response.data or b'RECIBO DE PAGO' in response.data
    with app.app_context():
        payment = Payment.query.one()
        promise = PaymentPromise.query.one()
        assert payment.receipt_code.startswith('CGP-')
        assert payment.reference == 'TRX-001'
        assert promise.status == 'fulfilled'
        assert promise.fulfilled_payment_id == payment.id
        assert TenantAuditLog.query.filter_by(action='payment.created').count() == 1


def test_expense_enters_cash_flow_report(client, app):
    register(client)
    response = client.post('/expenses', data={
        'expense_date': date.today().isoformat(), 'category': 'fuel', 'amount': '1250', 'method': 'cash', 'note': 'Ruta de cobro'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'1,250.00' in response.data
    report = client.get('/reports?period=today')
    assert report.status_code == 200
    assert b'Flujo neto' in report.data
    with app.app_context():
        assert Expense.query.count() == 1
        assert TenantAuditLog.query.filter_by(action='expense.created').count() == 1


def test_v116_initial_is_a_real_payment_with_receipt(client, app):
    register(client)
    client.post('/assets/new', data={
        'kind': 'phone', 'name': 'Equipo Inicial', 'quantity_total': '1', 'estimated_value': '60000'
    }, follow_redirects=True)
    with app.app_context():
        asset_id = Asset.query.filter_by(name='Equipo Inicial').one().id
    start = date.today()
    response = client.post('/contracts/new', data={
        'client_name': 'Cliente Inicial', 'asset_id': asset_id, 'quantity': '1',
        'deal_type': 'credit_sale', 'total_amount': '60000', 'down_payment': '10000',
        'down_payment_method': 'transfer', 'down_payment_reference': 'INI-001',
        'installment_count': '5', 'installment_amount': '10000', 'frequency': 'monthly',
        'start_date': start.isoformat(), 'first_due_date': (start + timedelta(days=30)).isoformat(),
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        contract = Contract.query.one()
        payment = Payment.query.one()
        assert payment.payment_kind == 'down_payment'
        assert payment.method == 'transfer'
        assert payment.reference == 'INI-001'
        assert payment.receipt_code.startswith('CGI-')
        assert contract.paid_total == Decimal('10000.00')
        assert contract.balance == Decimal('50000.00')
        payment_id = payment.id
    pdf = client.get(f'/payments/{payment_id}/receipt.pdf')
    assert pdf.status_code == 200
    assert pdf.mimetype == 'application/pdf'
    assert pdf.data.startswith(b'%PDF')


def test_v116_agreement_with_money_is_cancelled_not_deleted(client, app):
    register(client)
    client.post('/assets/new', data={
        'kind': 'phone', 'name': 'Equipo Historial', 'quantity_total': '1', 'estimated_value': '20000'
    }, follow_redirects=True)
    with app.app_context():
        asset_id = Asset.query.filter_by(name='Equipo Historial').one().id
    start = date.today()
    client.post('/contracts/new', data={
        'client_name': 'Cliente Historial', 'asset_id': asset_id, 'quantity': '1',
        'deal_type': 'credit_sale', 'total_amount': '20000', 'down_payment': '0',
        'installment_count': '4', 'installment_amount': '5000', 'frequency': 'monthly',
        'start_date': start.isoformat(), 'first_due_date': start.isoformat(),
    }, follow_redirects=True)
    with app.app_context():
        contract_id = Contract.query.one().id
    client.post(f'/contracts/{contract_id}/pay', data={
        'amount': '5000', 'method': 'cash', 'payment_kind': 'payment'
    }, follow_redirects=True)
    response = client.post(f'/contracts/{contract_id}/delete', data={'reason': 'Acuerdo anulado por corrección'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'pagos y recibos' in response.data.lower()
    with app.app_context():
        contract = db.session.get(Contract, contract_id)
        assert contract is not None
        assert contract.status == 'cancelled'
        assert contract.cancel_reason == 'Acuerdo anulado por corrección'
        assert Payment.query.filter_by(contract_id=contract_id).count() == 1
        assert db.session.get(Asset, asset_id).available_quantity == 1


def test_v116_roles_hide_sensitive_modules_and_enforce_routes(client, app):
    register(client)
    with app.app_context():
        user = User.query.filter_by(email='pavel@example.com').one()
        user.role = 'seller'
        db.session.commit()
    dashboard = client.get('/')
    assert dashboard.status_code == 200
    assert b'Reportes' not in dashboard.data
    assert b'Gastos' not in dashboard.data
    assert client.get('/clients').status_code == 200
    assert client.get('/contracts/new').status_code == 200
    assert client.get('/reports').status_code == 403
    assert client.get('/expenses').status_code == 403
    assert client.get('/purchases').status_code == 403


def test_v116_statement_has_real_pdf_and_hardening_assets():
    from pathlib import Path
    main = Path('cuotago/main.py').read_text(encoding='utf-8')
    base = Path('cuotago/templates/base.html').read_text(encoding='utf-8')
    css = Path('cuotago/static/css/app.css').read_text(encoding='utf-8')
    sw = Path('cuotago/static/service-worker.js').read_text(encoding='utf-8')
    init = Path('cuotago/__init__.py').read_text(encoding='utf-8')
    permissions = Path('cuotago/permissions.py').read_text(encoding='utf-8')
    assert '@main_bp.get("/clients/<int:client_id>/statement.pdf")' in main
    assert '@main_bp.get("/payments/<int:payment_id>/receipt.pdf")' in main
    assert 'data-share-pdf' in Path('cuotago/templates/clients/statement.html').read_text(encoding='utf-8')
    assert "1.17.0-ui-v35" in sw
    assert '-dark.png' in base
    assert 'schema_migrations' in init
    assert 'Strict-Transport-Security' in init
    assert 'Content-Security-Policy' in init
    assert 'ROLE_PERMISSIONS' in permissions
    assert '.topbar-search-v16' in css
    assert 'font-size:11px!important' in css


def test_v117_pwa_performance_and_calm_ux_are_wired():
    from pathlib import Path
    init = Path('cuotago/__init__.py').read_text(encoding='utf-8')
    main = Path('cuotago/main.py').read_text(encoding='utf-8')
    base = Path('cuotago/templates/base.html').read_text(encoding='utf-8')
    js = Path('cuotago/static/js/app.js').read_text(encoding='utf-8')
    css = Path('cuotago/static/css/app.css').read_text(encoding='utf-8')
    sw = Path('cuotago/static/service-worker.js').read_text(encoding='utf-8')
    models = Path('cuotago/models.py').read_text(encoding='utf-8')
    requirements = Path('requirements.txt').read_text(encoding='utf-8')
    assert 'navigationPreload.enable()' in sw
    assert "1.17.0-ui-v35" in sw
    assert 'data-global-search-open' in base
    assert 'setupGlobalQuickSearch' in js
    assert 'setupCalmFormGuard' in js
    assert 'Server-Timing' in init
    assert 'image_thumb_data' in models
    assert 'request_key' in models
    assert 'Flask-Compress' in requirements
    assert 'Pillow' in requirements
    assert 'expense.voided' in main
    assert '.quick-search-dialog-v17' in css
