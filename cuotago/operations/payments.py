"""Payment allocation evidence and explicit, non-destructive reversals."""
import json
from decimal import Decimal
from ..business_time import business_date, utcnow
from ..money_ops import money
from ..models import Contract, Installment, Payment, PaymentPromise
from .models import PaymentAllocation, PaymentReversal
from .common import audit
from .cash import reverse_entry


def allocation_snapshot(contract):
    return {i.id: {'principal': money(i.paid_amount), 'fee': money(i.late_fee_paid),
                   'principal_at': i.principal_paid_at, 'paid_at': i.paid_at}
            for i in contract.installments}


def save_allocations(s, contract, payment, before):
    payment.allocation_version = 1
    for item in contract.installments:
        prior = before[item.id]
        principal = money(item.paid_amount) - prior['principal']
        fee = money(item.late_fee_paid) - prior['fee']
        if principal or fee:
            s.add(PaymentAllocation(payment_id=payment.id, installment_id=item.id,
                  sequence=item.sequence, due_date=item.due_date, principal=principal, late_fee=fee,
                  principal_paid_at_before=prior['principal_at'], paid_at_before=prior['paid_at']))


def reverse_payment(s, org, actor, contract, payment_id, reason, zone):
    """Caller has taken stock -> contract locks and checked payments.reverse.

    Historical/unmapped portions become an explicit correction installment due
    today. They are not guessed or retroactively charged interest. Existing
    allocation rows are retained. Original receipt and money never get deleted.
    """
    if contract.organization_id != org:
        raise LookupError('Acuerdo no encontrado.')
    payment = s.query(Payment).filter_by(id=payment_id, contract_id=contract.id).with_for_update(of=Payment).first()
    if payment is None:
        raise LookupError('Pago no encontrado.')
    if payment.voided_at:
        raise ValueError('El pago ya fue revertido.')
    reason = (reason or '').strip()
    if len(reason) < 5 or len(reason) > 240:
        raise ValueError('Escribe un motivo de 5 a 240 caracteres.')
    now = utcnow()
    today = business_date(now, zone)
    evidence = s.query(PaymentAllocation).filter_by(payment_id=payment.id).order_by(PaymentAllocation.id).all()
    principal = money(payment.amount) - money(payment.late_fee_amount)
    fee = money(payment.late_fee_amount)
    if principal < 0:
        raise ValueError('El pago contiene una distribucion inconsistente. Requiere conciliacion.')
    restored_p = Decimal('0.00')
    restored_f = Decimal('0.00')
    touched = []
    for allocation in evidence:
        item = s.get(Installment, allocation.installment_id) if allocation.installment_id else None
        if item is None:
            continue
        if item.contract_id != contract.id:
            raise ValueError('Asignacion de pago inconsistente.')
        if money(item.paid_amount) < allocation.principal or money(item.late_fee_paid) < allocation.late_fee:
            raise ValueError('El calendario cambio de forma incompatible. Revisa auditoria.')
        item.paid_amount = money(item.paid_amount - allocation.principal)
        item.late_fee_paid = money(item.late_fee_paid - allocation.late_fee)
        if item.principal_remaining > 0:
            item.principal_paid_at = None
            # Freeze accrued fees and resume from reversal day, not original due date.
            item.late_fee_base_amount = money(item.late_fee_amount)
            item.late_fee_reset_on = today
        if item.remaining > 0:
            item.paid_at = None
        restored_p += allocation.principal
        restored_f += allocation.late_fee
        touched.append(item.id)
    missing_p, missing_f = money(principal - restored_p), money(fee - restored_f)
    if missing_p < 0 or missing_f < 0:
        raise ValueError('Las asignaciones superan el pago original.')
    adjustment = None
    if missing_p or missing_f:
        # Legacy payments, original down payments or schedules replaced before
        # v83 need an explicit outstanding correction, not an invented allocation.
        adjustment = Installment(contract=contract,
            sequence=max((i.sequence for i in contract.installments), default=0) + 1,
            due_date=today, amount=missing_p, paid_amount=0,
            late_fee_amount=missing_f, late_fee_base_amount=missing_f, late_fee_paid=0,
            late_fee_reset_on=today)
        s.add(adjustment)
        s.flush()
    payment.voided_at, payment.voided_by_user_id, payment.void_reason = now, actor, reason
    if contract.status == 'completed':
        if contract.deal_type != 'credit_sale':
            contract.inventory_released = True
        contract.status = 'active'
    for promise in s.query(PaymentPromise).filter_by(organization_id=org,
            contract_id=contract.id, fulfilled_payment_id=payment.id, status='fulfilled').all():
        promise.status = 'broken' if promise.promised_date < today else 'pending'
        promise.fulfilled_payment_id = None
        promise.fulfilled_at = None
    detail = {'original_receipt': payment.receipt_code, 'principal': str(principal),
              'late_fee': str(fee), 'installments': touched,
              'correction_installment': adjustment.id if adjustment else None,
              'historical_allocation': payment.allocation_version == 0,
              'interest_policy': 'No retroactive additional fees; resume today.'}
    reversal = PaymentReversal(organization_id=org, contract_id=contract.id,
        payment_id=payment.id, amount=payment.amount, late_fee_amount=payment.late_fee_amount,
        reason=reason, actor_id=actor, reversed_at=now, detail=json.dumps(detail))
    s.add(reversal)
    s.flush()
    reversal.code = f'CGR-{org}-{reversal.id:06d}'
    reverse_entry(s, org, actor, 'payment_reversal', reversal.id, 'payment', payment.id, -money(payment.amount),
        payment.method, f'Reversion {reversal.code} de {payment.receipt_code}', payment.reference, now)
    audit(s, org, actor, 'payment.reversed', 'payment', payment.id, f'Pago revertido: {reason}', detail)
    return reversal
