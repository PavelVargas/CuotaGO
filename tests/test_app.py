from datetime import date, timedelta
from decimal import Decimal
import os

import pytest

from cuotago import create_app
from cuotago.extensions import db
from cuotago.models import Asset, Client, Contract, Installment, PushSubscription, User


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
    assert b"Nuevo acuerdo" in response.data
    with app.app_context():
        assert User.query.count() == 1


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
