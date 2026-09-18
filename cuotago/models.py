from datetime import datetime
from decimal import Decimal

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


def now_utc_naive():
    return datetime.utcnow()


class Organization(db.Model):
    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    currency = db.Column(db.String(8), nullable=False, default="DOP")
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)

    users = db.relationship("User", back_populates="organization", cascade="all, delete-orphan")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(160), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="owner")
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)

    organization = db.relationship("Organization", back_populates="users")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    full_name = db.Column(db.String(140), nullable=False)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(160))
    document_id = db.Column(db.String(80))
    address = db.Column(db.String(240))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)

    contracts = db.relationship("Contract", back_populates="client")


class Asset(db.Model):
    __tablename__ = "assets"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    kind = db.Column(db.String(40), nullable=False, default="otro")
    name = db.Column(db.String(140), nullable=False)
    brand = db.Column(db.String(80))
    model = db.Column(db.String(100))
    identifier = db.Column(db.String(120))
    serial_number = db.Column(db.String(120))
    estimated_value = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="available")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)

    contracts = db.relationship("Contract", back_populates="asset")


class Contract(db.Model):
    __tablename__ = "contracts"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False, index=True)
    code = db.Column(db.String(40), unique=True, index=True)
    deal_type = db.Column(db.String(30), nullable=False, default="credit_sale")
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    down_payment = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    installment_amount = db.Column(db.Numeric(12, 2), nullable=False)
    frequency = db.Column(db.String(20), nullable=False, default="monthly")
    start_date = db.Column(db.Date, nullable=False)
    first_due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="active")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)

    client = db.relationship("Client", back_populates="contracts")
    asset = db.relationship("Asset", back_populates="contracts")
    installments = db.relationship(
        "Installment",
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="Installment.due_date.asc()",
    )
    payments = db.relationship(
        "Payment",
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="Payment.paid_at.desc()",
    )

    @property
    def payments_total(self):
        return sum((Decimal(str(p.amount or 0)) for p in self.payments), Decimal("0.00"))

    @property
    def paid_total(self):
        return Decimal(str(self.down_payment or 0)) + self.payments_total

    @property
    def balance(self):
        value = Decimal(str(self.total_amount or 0)) - self.paid_total
        return max(value, Decimal("0.00"))

    @property
    def progress_percent(self):
        total = Decimal(str(self.total_amount or 0))
        if total <= 0:
            return 100
        value = (self.paid_total / total) * Decimal("100")
        return float(min(max(value, 0), 100))

    @property
    def next_installment(self):
        for installment in self.installments:
            if installment.remaining > Decimal("0.009"):
                return installment
        return None


class Installment(db.Model):
    __tablename__ = "installments"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), nullable=False, index=True)
    sequence = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    paid_at = db.Column(db.DateTime)

    contract = db.relationship("Contract", back_populates="installments")

    @property
    def remaining(self):
        return max(
            Decimal(str(self.amount or 0)) - Decimal(str(self.paid_amount or 0)),
            Decimal("0.00"),
        )

    @property
    def is_paid(self):
        return self.remaining <= Decimal("0.009")


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(30), nullable=False, default="cash")
    note = db.Column(db.String(240))
    paid_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False, index=True)

    contract = db.relationship("Contract", back_populates="payments")


class PushSubscription(db.Model):
    __tablename__ = "push_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.Text, nullable=False)
    auth = db.Column(db.Text, nullable=False)
    user_agent = db.Column(db.String(300))
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)


class PushNotificationLog(db.Model):
    __tablename__ = "push_notification_logs"
    __table_args__ = (
        db.UniqueConstraint("installment_id", "event_type", name="uq_push_installment_event"),
    )

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    installment_id = db.Column(db.Integer, db.ForeignKey("installments.id"), nullable=False, index=True)
    event_type = db.Column(db.String(40), nullable=False)
    sent_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)
