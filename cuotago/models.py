from datetime import date, datetime
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy.orm import deferred
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
    subscription = db.relationship(
        "OrganizationSubscription",
        back_populates="organization",
        cascade="all, delete-orphan",
        uselist=False,
    )


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(160), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="owner")
    is_enabled = db.Column(db.Boolean, nullable=False, default=True, index=True)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)

    organization = db.relationship("Organization", back_populates="users")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return bool(self.is_enabled)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


class SubscriptionPlan(db.Model):
    __tablename__ = "subscription_plans"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), nullable=False, unique=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    currency = db.Column(db.String(8), nullable=False, default="DOP")
    billing_interval_months = db.Column(db.Integer, nullable=False, default=1)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)
    updated_at = db.Column(db.DateTime, default=now_utc_naive, onupdate=now_utc_naive, nullable=False)

    subscriptions = db.relationship("OrganizationSubscription", back_populates="plan")


class OrganizationSubscription(db.Model):
    __tablename__ = "organization_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=False, unique=True, index=True
    )
    plan_id = db.Column(db.Integer, db.ForeignKey("subscription_plans.id"), nullable=True, index=True)
    status = db.Column(db.String(24), nullable=False, default="pending", index=True)
    amount_override = db.Column(db.Numeric(12, 2))
    current_period_start = db.Column(db.Date)
    current_period_end = db.Column(db.Date, index=True)
    grace_ends_at = db.Column(db.Date)
    notes = db.Column(db.Text)
    last_payment_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)
    updated_at = db.Column(db.DateTime, default=now_utc_naive, onupdate=now_utc_naive, nullable=False)

    organization = db.relationship("Organization", back_populates="subscription")
    plan = db.relationship("SubscriptionPlan", back_populates="subscriptions")
    payments = db.relationship(
        "SubscriptionPayment",
        back_populates="subscription",
        cascade="all, delete-orphan",
        order_by="SubscriptionPayment.paid_at.desc()",
    )

    @property
    def effective_amount(self):
        if self.amount_override is not None:
            return Decimal(str(self.amount_override or 0))
        if self.plan is not None:
            return Decimal(str(self.plan.price or 0))
        return Decimal("0.00")

    @property
    def effective_status(self):
        status = (self.status or "pending").strip().lower()
        if status in {"suspended", "cancelled"}:
            return status
        today = date.today()
        if self.current_period_end and self.current_period_end < today:
            if self.grace_ends_at and self.grace_ends_at >= today:
                return "past_due"
            return "expired"
        return status

    @property
    def days_remaining(self):
        if not self.current_period_end:
            return None
        return (self.current_period_end - date.today()).days


class SubscriptionPayment(db.Model):
    __tablename__ = "subscription_payments"

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(
        db.Integer, db.ForeignKey("organization_subscriptions.id"), nullable=False, index=True
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(8), nullable=False, default="DOP")
    method = db.Column(db.String(30), nullable=False, default="cash")
    reference = db.Column(db.String(120))
    note = db.Column(db.String(240))
    period_start = db.Column(db.Date)
    period_end = db.Column(db.Date)
    previous_period_start = db.Column(db.Date)
    previous_period_end = db.Column(db.Date)
    previous_status = db.Column(db.String(24))
    paid_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, nullable=True, index=True)
    voided_at = db.Column(db.DateTime, index=True)
    voided_by_user_id = db.Column(db.Integer, nullable=True, index=True)
    void_reason = db.Column(db.String(240))

    subscription = db.relationship("OrganizationSubscription", back_populates="payments")


class AdminAuditLog(db.Model):
    __tablename__ = "admin_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, nullable=True, index=True)
    organization_id = db.Column(db.Integer, nullable=True, index=True)
    action = db.Column(db.String(60), nullable=False, index=True)
    target_type = db.Column(db.String(40), nullable=False, default="organization")
    target_id = db.Column(db.String(80))
    summary = db.Column(db.String(240), nullable=False)
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False, index=True)


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
    collection_notes = db.relationship(
        "CollectionNote", back_populates="client", cascade="all, delete-orphan", order_by="CollectionNote.created_at.desc()"
    )
    payment_promises = db.relationship(
        "PaymentPromise", back_populates="client", cascade="all, delete-orphan", order_by="PaymentPromise.promised_date.desc()"
    )


class Supplier(db.Model):
    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    name = db.Column(db.String(140), nullable=False)
    phone = db.Column(db.String(40))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)

    purchases = db.relationship("Purchase", back_populates="supplier_record")


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
    # ``estimated_value`` is kept as the acquisition/base cost for backward
    # compatibility with existing agreements and reports. ``sale_price`` is
    # the target cash/credit selling price per unit.
    estimated_value = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    sale_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    quantity_total = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(30), nullable=False, default="available")
    notes = db.Column(db.Text)
    image_mime = db.Column(db.String(80))
    image_data = deferred(db.Column(db.LargeBinary))
    image_thumb_data = deferred(db.Column(db.LargeBinary))
    image_updated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)

    contracts = db.relationship("Contract", back_populates="asset")
    purchases = db.relationship("Purchase", back_populates="asset", order_by="Purchase.purchase_date.desc()")

    @property
    def expected_profit_per_unit(self):
        return Decimal(str(self.sale_price or 0)) - Decimal(str(self.estimated_value or 0))

    @property
    def expected_margin_percent(self):
        cost = Decimal(str(self.estimated_value or 0))
        if cost <= 0:
            return Decimal("0.00")
        return ((self.expected_profit_per_unit / cost) * Decimal("100")).quantize(Decimal("0.01"))

    @property
    def committed_quantity(self):
        total = 0
        for contract in self.contracts:
            qty = max(int(contract.quantity or 1), 1)
            if contract.status == "active" or (contract.status == "completed" and contract.deal_type == "credit_sale"):
                total += qty
        return total

    @property
    def available_quantity(self):
        return max(int(self.quantity_total or 1) - self.committed_quantity, 0)


class Purchase(db.Model):
    __tablename__ = "purchases"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True, index=True)
    batch_key = db.Column(db.String(36), index=True)
    supplier = db.Column(db.String(140))
    reference = db.Column(db.String(120))
    purchase_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    unit_sale_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)

    asset = db.relationship("Asset", back_populates="purchases")
    supplier_record = db.relationship("Supplier", back_populates="purchases")

    @property
    def total_cost(self):
        return Decimal(str(self.unit_cost or 0)) * Decimal(int(self.quantity or 0))

    @property
    def expected_revenue(self):
        # Purchases only capture acquisition cost. Margin is derived from the
        # current inventory selling price; legacy rows may still carry a sale
        # price snapshot. If neither exists, keep the row neutral instead of
        # reporting a fake loss.
        current_sale_price = Decimal(str(self.asset.sale_price or 0)) if self.asset is not None else Decimal("0")
        legacy_sale_price = Decimal(str(self.unit_sale_price or 0))
        effective_sale_price = current_sale_price if current_sale_price > 0 else legacy_sale_price
        if effective_sale_price <= 0:
            effective_sale_price = Decimal(str(self.unit_cost or 0))
        return effective_sale_price * Decimal(int(self.quantity or 0))

    @property
    def expected_profit(self):
        return self.expected_revenue - self.total_cost

    @property
    def margin_percent(self):
        cost = self.total_cost
        if cost <= 0:
            return Decimal("0.00")
        return ((self.expected_profit / cost) * Decimal("100")).quantize(Decimal("0.01"))


class Contract(db.Model):
    __tablename__ = "contracts"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False, index=True)
    code = db.Column(db.String(40), unique=True, index=True)
    request_key = db.Column(db.String(64), unique=True, index=True)
    deal_type = db.Column(db.String(30), nullable=False, default="credit_sale")
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    base_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    profit_margin_percent = db.Column(db.Numeric(7, 2), nullable=False, default=0)
    down_payment = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    installment_amount = db.Column(db.Numeric(12, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    daily_late_interest = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    # When mora is enabled after creation, charges start from this day instead
    # of being backdated to an older overdue installment. Legacy agreements
    # with mora and a NULL value keep their original behavior via start_date.
    late_fee_started_on = db.Column(db.Date, nullable=True)
    frequency = db.Column(db.String(20), nullable=False, default="monthly")
    start_date = db.Column(db.Date, nullable=False)
    first_due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="active")
    notes = db.Column(db.Text)
    cancelled_at = db.Column(db.DateTime, nullable=True, index=True)
    cancelled_by_user_id = db.Column(db.Integer, nullable=True, index=True)
    cancel_reason = db.Column(db.String(240))
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
    payment_promises = db.relationship(
        "PaymentPromise", back_populates="contract", cascade="all, delete-orphan", order_by="PaymentPromise.promised_date.desc()"
    )
    schedule_changes = db.relationship(
        "ContractScheduleChange", back_populates="contract", cascade="all, delete-orphan", order_by="ContractScheduleChange.created_at.desc()"
    )

    @property
    def profit_amount(self):
        base = Decimal(str(self.base_amount or 0))
        total = Decimal(str(self.total_amount or 0))
        return max(total - base, Decimal("0.00"))

    @property
    def payments_total(self):
        return sum((Decimal(str(p.amount or 0)) for p in self.payments), Decimal("0.00"))

    @property
    def interest_paid_total(self):
        return sum((Decimal(str(p.late_fee_amount or 0)) for p in self.payments), Decimal("0.00"))

    @property
    def principal_payments_total(self):
        return max(self.payments_total - self.interest_paid_total, Decimal("0.00"))

    @property
    def principal_paid_total(self):
        # Since v1.16 the initial payment is a real Payment row.  The schema
        # upgrader backfills legacy initials, so every received peso follows
        # the same receipt/audit path.
        return self.principal_payments_total

    @property
    def paid_total(self):
        # Dinero realmente recibido, incluyendo iniciales y recargos.
        return self.payments_total

    @property
    def principal_balance(self):
        value = Decimal(str(self.total_amount or 0)) - self.principal_paid_total
        return max(value, Decimal("0.00"))

    @property
    def late_fee_balance(self):
        return sum((i.late_fee_remaining for i in self.installments), Decimal("0.00"))

    @property
    def balance(self):
        return self.principal_balance + self.late_fee_balance

    @property
    def progress_percent(self):
        total = Decimal(str(self.total_amount or 0))
        if total <= 0:
            return 100
        value = (self.principal_paid_total / total) * Decimal("100")
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
    late_fee_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    late_fee_base_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    late_fee_paid = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    principal_paid_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)

    contract = db.relationship("Contract", back_populates="installments")

    @property
    def principal_remaining(self):
        return max(
            Decimal(str(self.amount or 0)) - Decimal(str(self.paid_amount or 0)),
            Decimal("0.00"),
        )

    @property
    def late_fee_remaining(self):
        return max(
            Decimal(str(self.late_fee_amount or 0)) - Decimal(str(self.late_fee_paid or 0)),
            Decimal("0.00"),
        )

    @property
    def remaining(self):
        return self.principal_remaining + self.late_fee_remaining

    @property
    def is_paid(self):
        return self.remaining <= Decimal("0.009")

    @property
    def principal_is_paid(self):
        return self.principal_remaining <= Decimal("0.009")


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    late_fee_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    method = db.Column(db.String(30), nullable=False, default="cash")
    reference = db.Column(db.String(120))
    payment_kind = db.Column(db.String(24), nullable=False, default="payment")
    receipt_code = db.Column(db.String(60), unique=True, index=True)
    request_key = db.Column(db.String(64), unique=True, index=True)
    created_by_user_id = db.Column(db.Integer, nullable=True, index=True)
    note = db.Column(db.String(240))
    paid_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False, index=True)

    contract = db.relationship("Contract", back_populates="payments")


class CollectionNote(db.Model):
    __tablename__ = "collection_notes"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True, index=True)
    body = db.Column(db.Text, nullable=False)
    created_by_user_id = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False, index=True)

    client = db.relationship("Client", back_populates="collection_notes")


class PaymentPromise(db.Model):
    __tablename__ = "payment_promises"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True, index=True)
    promised_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    note = db.Column(db.String(240))
    created_by_user_id = db.Column(db.Integer, nullable=True, index=True)
    fulfilled_payment_id = db.Column(db.Integer, nullable=True, index=True)
    fulfilled_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=now_utc_naive, onupdate=now_utc_naive, nullable=False)

    client = db.relationship("Client", back_populates="payment_promises")
    contract = db.relationship("Contract", back_populates="payment_promises")


class ContractScheduleChange(db.Model):
    __tablename__ = "contract_schedule_changes"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, nullable=True, index=True)
    reason = db.Column(db.String(240))
    old_frequency = db.Column(db.String(20))
    new_frequency = db.Column(db.String(20))
    old_next_due_date = db.Column(db.Date)
    new_next_due_date = db.Column(db.Date)
    old_open_count = db.Column(db.Integer, nullable=False, default=0)
    new_open_count = db.Column(db.Integer, nullable=False, default=0)
    pending_principal = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    pending_late_fee = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    snapshot = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False, index=True)

    contract = db.relationship("Contract", back_populates="schedule_changes")


class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    expense_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    category = db.Column(db.String(60), nullable=False, default="other", index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(30), nullable=False, default="cash")
    reference = db.Column(db.String(120))
    note = db.Column(db.String(240))
    created_by_user_id = db.Column(db.Integer, nullable=True, index=True)
    voided_at = db.Column(db.DateTime, index=True)
    voided_by_user_id = db.Column(db.Integer, nullable=True, index=True)
    void_reason = db.Column(db.String(240))
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False, index=True)


class TenantAuditLog(db.Model):
    __tablename__ = "tenant_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, nullable=True, index=True)
    action = db.Column(db.String(60), nullable=False, index=True)
    entity_type = db.Column(db.String(40), nullable=False, index=True)
    entity_id = db.Column(db.String(80))
    summary = db.Column(db.String(240), nullable=False)
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False, index=True)


class AuthRateLimit(db.Model):
    __tablename__ = "auth_rate_limits"

    id = db.Column(db.Integer, primary_key=True)
    key_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    window_started_at = db.Column(db.DateTime, default=now_utc_naive, nullable=False)
    blocked_until = db.Column(db.DateTime, nullable=True, index=True)
    updated_at = db.Column(db.DateTime, default=now_utc_naive, onupdate=now_utc_naive, nullable=False)


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
