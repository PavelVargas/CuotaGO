"""Immutable monetary journal and per-user cash shifts, with register row locking."""
from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from ..models import User
from ..business_time import utcnow
from ..money_ops import money
from .models import OrganizationControls, CashRegister, CashShift, MoneyEntry
from .common import audit, scoped

METHODS = {'cash', 'transfer', 'deposit', 'card', 'other'}


def lock_register(s, org, actor):
    # Serialize first register creation using the user row, not a read-then-insert.
    user = s.query(User).filter_by(id=actor, organization_id=org).with_for_update(of=User).first()
    if user is None:
        raise LookupError('Usuario no encontrado.')
    row = s.query(CashRegister).filter_by(organization_id=org, user_id=actor).populate_existing().with_for_update(of=CashRegister).first()
    if row is None:
        row = CashRegister(organization_id=org, user_id=actor)
        s.add(row)
        s.flush()
    return row


def post_entry(s, org, actor, source_type, source_id, amount, method, description,
               reference=None, occurred_at=None):
    value = money(amount)
    if value == 0:
        return None
    if method not in METHODS:
        raise ValueError('Medio de pago no valido.')
    prior = s.query(MoneyEntry).filter_by(organization_id=org, source_type=source_type, source_id=str(source_id)).first()
    if prior:
        if money(prior.amount) != value or prior.method != method:
            raise ValueError('El origen monetario ya existe con otro importe.')
        return prior
    shift_id = None
    if method == 'cash':
        register = lock_register(s, org, actor)
        shift_id = register.current_shift_id
        control = s.get(OrganizationControls, org)
        if control and control.require_cash_shift and shift_id is None:
            raise ValueError('Abre tu caja antes de registrar efectivo. No se guardo ningun movimiento.')
        if shift_id:
            shift = scoped(s, CashShift, org, shift_id)
            if shift.closed_at is not None or shift.user_id != actor:
                raise ValueError('La caja ya esta cerrada. Abre una nueva.')
    row = MoneyEntry(organization_id=org, actor_id=actor, cash_shift_id=shift_id,
                    source_type=source_type, source_id=str(source_id), amount=value,
                    method=method, reference=(reference or '')[:120] or None,
                    description=description[:240], occurred_at=occurred_at or utcnow())
    s.add(row)
    s.flush()
    return row


def open_shift(s, org, actor, opening):
    opening = money(opening)
    if opening < 0:
        raise ValueError('El fondo inicial no puede ser negativo.')
    register = lock_register(s, org, actor)
    if register.current_shift_id:
        raise ValueError('Ya tienes una caja abierta.')
    shift = CashShift(organization_id=org, user_id=actor, opening=opening)
    s.add(shift)
    s.flush()
    register.current_shift_id = shift.id
    audit(s, org, actor, 'cash.opened', 'cash_shift', shift.id, 'Caja abierta.', {'opening': opening})
    return shift


def expected_cash(s, shift):
    total = s.query(func.coalesce(func.sum(MoneyEntry.amount), 0)).filter_by(
        organization_id=shift.organization_id, cash_shift_id=shift.id, method='cash').scalar()
    return money(shift.opening + money(total))


def close_shift(s, org, actor, shift_id, counted, note, allow_other=False):
    # Observe owner first; all mutations lock register before shift.
    shift = scoped(s, CashShift, org, shift_id)
    if shift.user_id != actor and not allow_other:
        raise PermissionError('Solo puedes cerrar tu propia caja.')
    register = lock_register(s, org, shift.user_id)
    shift = scoped(s, CashShift, org, shift_id, lock=True)
    if shift.closed_at or register.current_shift_id != shift.id:
        raise ValueError('La caja ya fue cerrada; el cierre no se modifica.')
    counted = money(counted)
    if counted < 0:
        raise ValueError('El efectivo contado no puede ser negativo.')
    expected = expected_cash(s, shift)
    difference = money(counted - expected)
    if difference != 0 and len((note or '').strip()) < 5:
        raise ValueError('Explica la diferencia antes de cerrar la caja.')
    shift.expected, shift.counted, shift.difference = expected, counted, difference
    shift.closed_at, shift.closed_by_user_id = utcnow(), actor
    shift.note = (note or '').strip()[:240]
    register.current_shift_id = None
    audit(s, org, actor, 'cash.closed', 'cash_shift', shift.id, 'Caja cerrada con arqueo.',
          {'expected': expected, 'counted': counted, 'difference': difference, 'note': shift.note})
    return shift


def reverse_entry(s, org, actor, source_type, source_id, original_type, original_id,
                  amount, method, description, reference=None, occurred_at=None):
    """Correct the original register only if it is still open.

    A closed count is immutable. Its correction (or a pre-v83 correction) is
    unassigned to a current drawer: it must not remove money from the operator
    who merely authorized a bookkeeping correction. No physical/bank refund is
    executed. Any actual later cash disbursement is a separate documented task.
    """
    value = money(amount)
    if method not in METHODS or not value:
        raise ValueError('Movimiento inverso no valido.')
    prior = s.query(MoneyEntry).filter_by(organization_id=org, source_type=source_type,
                                         source_id=str(source_id)).first()
    if prior:
        if money(prior.amount) != value or prior.method != method:
            raise ValueError('La correccion ya existe con otro importe.')
        return prior
    original = s.query(MoneyEntry).filter_by(organization_id=org,
        source_type=original_type, source_id=str(original_id)).first()
    shift_id = None
    if original:
        if money(original.amount) != -value or original.method != method:
            raise ValueError('El movimiento original no coincide. Requiere conciliacion.')
        if method == 'cash' and original.cash_shift_id:
            observed = scoped(s, CashShift, org, original.cash_shift_id)
            register = lock_register(s, org, observed.user_id)
            observed = scoped(s, CashShift, org, observed.id, lock=True)
            if observed.closed_at is None and register.current_shift_id == observed.id:
                shift_id = observed.id
    row = MoneyEntry(organization_id=org, actor_id=actor, cash_shift_id=shift_id,
        source_type=source_type, source_id=str(source_id), amount=value, method=method,
        description=description[:240], reference=(reference or '')[:120] or None,
        occurred_at=occurred_at or utcnow())
    s.add(row);s.flush()
    return row
