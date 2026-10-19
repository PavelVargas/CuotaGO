from ..extensions import db
from ..business_time import utcnow


class OperationRequest(db.Model):
    __tablename__ = 'operation_requests'
    __table_args__ = (db.UniqueConstraint('organization_id', 'scope', 'request_key', name='uq_operation_request'),)
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    scope = db.Column(db.String(40), nullable=False)
    request_key = db.Column(db.String(64), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    result_id = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class UserSession(db.Model):
    __tablename__ = 'user_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    label = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)


class UserMFA(db.Model):
    __tablename__ = 'user_mfa'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    encrypted_secret = db.Column(db.Text, nullable=False)
    enabled_at = db.Column(db.DateTime)
    setup_expires_at = db.Column(db.DateTime)
    last_counter = db.Column(db.BigInteger, nullable=False, default=-1)
    recovery_hashes = db.Column(db.Text, nullable=False, default='[]')


class OrganizationControls(db.Model):
    __tablename__ = 'organization_controls'
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), primary_key=True)
    require_cash_shift = db.Column(db.Boolean, nullable=False, default=False)
    collectors_restricted = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class PaymentAllocation(db.Model):
    __tablename__ = 'payment_allocations'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False, index=True)
    # SET NULL preserves evidence if an old schedule is replaced; reversal then
    # creates a documented correction installment rather than guessing history.
    installment_id = db.Column(db.Integer, db.ForeignKey('installments.id', ondelete='SET NULL'), index=True)
    sequence = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    principal = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    late_fee = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    principal_paid_at_before = db.Column(db.DateTime)
    paid_at_before = db.Column(db.DateTime)


class PaymentReversal(db.Model):
    __tablename__ = 'payment_reversals'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False, unique=True)
    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    late_fee_amount = db.Column(db.Numeric(12, 2), nullable=False)
    reason = db.Column(db.String(240), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reversed_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    code = db.Column(db.String(60), unique=True)
    detail = db.Column(db.Text, nullable=False)
    payment = db.relationship('Payment', backref=db.backref('reversal', uselist=False))


class CashRegister(db.Model):
    __tablename__ = 'cash_registers'
    __table_args__ = (db.UniqueConstraint('organization_id', 'user_id', name='uq_register_user'),)
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    current_shift_id = db.Column(db.Integer, nullable=True)


class CashShift(db.Model):
    __tablename__ = 'cash_shifts'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    opened_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    closed_at = db.Column(db.DateTime, index=True)
    opening = db.Column(db.Numeric(12, 2), nullable=False)
    expected = db.Column(db.Numeric(12, 2))
    counted = db.Column(db.Numeric(12, 2))
    difference = db.Column(db.Numeric(12, 2))
    note = db.Column(db.String(240))
    closed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user = db.relationship('User', foreign_keys=[user_id])


class MoneyEntry(db.Model):
    __tablename__ = 'money_entries'
    __table_args__ = (db.UniqueConstraint('organization_id', 'source_type', 'source_id', name='uq_money_source'),)
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    cash_shift_id = db.Column(db.Integer, db.ForeignKey('cash_shifts.id'), nullable=True, index=True)
    source_type = db.Column(db.String(40), nullable=False)
    source_id = db.Column(db.String(80), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(30), nullable=False)
    reference = db.Column(db.String(120))
    description = db.Column(db.String(240), nullable=False)
    occurred_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_orders'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False, index=True)
    reference = db.Column(db.String(120))
    expected_on = db.Column(db.Date)
    state = db.Column(db.String(20), nullable=False, default='sent', index=True)
    note = db.Column(db.String(240))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    supplier = db.relationship('Supplier')
    lines = db.relationship('PurchaseOrderLine', back_populates='order', order_by='PurchaseOrderLine.id')
    payments = db.relationship('SupplierPayment', back_populates='order')


class PurchaseOrderLine(db.Model):
    __tablename__ = 'purchase_order_lines'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), nullable=False, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'))
    name = db.Column(db.String(140), nullable=False)
    kind = db.Column(db.String(40), nullable=False, default='other')
    quantity = db.Column(db.Integer, nullable=False)
    received = db.Column(db.Integer, nullable=False, default=0)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False)
    order = db.relationship('PurchaseOrder', back_populates='lines')
    asset = db.relationship('Asset')


class OrderReceipt(db.Model):
    __tablename__ = 'order_receipts'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), nullable=False, index=True)
    line_id = db.Column(db.Integer, db.ForeignKey('purchase_order_lines.id'), nullable=False)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'), nullable=False, unique=True)
    quantity = db.Column(db.Integer, nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    received_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class SupplierPayment(db.Model):
    __tablename__ = 'supplier_payments'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(30), nullable=False)
    reference = db.Column(db.String(120))
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    paid_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    voided_at = db.Column(db.DateTime)
    void_reason = db.Column(db.String(240))
    order = db.relationship('PurchaseOrder', back_populates='payments')


class PortalGrant(db.Model):
    __tablename__ = 'portal_grants'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)


class ImportBatch(db.Model):
    __tablename__ = 'import_batches'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    digest = db.Column(db.String(64), nullable=False)
    payload = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    applied_at = db.Column(db.DateTime)
    applied_count = db.Column(db.Integer)


class BankLine(db.Model):
    __tablename__ = 'bank_lines'
    __table_args__ = (db.UniqueConstraint('organization_id', 'account', 'external_id', name='uq_bank_line'),)
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    account = db.Column(db.String(80), nullable=False)
    external_id = db.Column(db.String(120), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reference = db.Column(db.String(120))
    money_entry_id = db.Column(db.Integer, db.ForeignKey('money_entries.id'), unique=True)
    matched_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    matched_at = db.Column(db.DateTime)
    batch_id = db.Column(db.Integer, db.ForeignKey('import_batches.id'), nullable=False)
    money_entry = db.relationship('MoneyEntry')
