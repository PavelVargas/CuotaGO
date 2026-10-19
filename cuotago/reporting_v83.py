"""SQL summaries over receipt/reversal events, classified by business timezone."""
from decimal import Decimal
from sqlalchemy import select, union_all, func, literal
from .models import Payment, Contract
from .operations.models import PaymentReversal, MoneyEntry
from .business_time import utc_bounds, business_date
from .money_ops import money


def receipt_events(contract_ids):
    original = select(Payment.id.label('payment_id'), Payment.contract_id.label('contract_id'),
        Payment.amount.label('amount'), Payment.late_fee_amount.label('late_fee'),
        Payment.method.label('method'), Payment.payment_kind.label('kind'),
        Payment.paid_at.label('at'), literal(False).label('reversal')).where(Payment.contract_id.in_(contract_ids))
    reverse = select(PaymentReversal.payment_id, PaymentReversal.contract_id,
        -PaymentReversal.amount, -PaymentReversal.late_fee_amount, Payment.method,
        Payment.payment_kind, PaymentReversal.reversed_at, literal(True)).join(
            Payment, Payment.id == PaymentReversal.payment_id).where(PaymentReversal.contract_id.in_(contract_ids))
    return union_all(original, reverse).subquery('receipt_events')


def payment_summary(s, contract_ids, first, last, zone):
    e = receipt_events(contract_ids)
    start, end = utc_bounds(first, last, zone)
    filters = [e.c.at < end]
    if start:
        filters.append(e.c.at >= start)
    scoped = select(e).where(*filters).subquery('period_receipts')
    total = money(s.execute(select(func.coalesce(func.sum(scoped.c.amount), 0))).scalar())
    count, gross = s.execute(select(func.count(), func.coalesce(func.sum(scoped.c.amount), 0)).where(scoped.c.reversal == False)).one()
    methods = {m: money(v) for m, v in s.execute(select(scoped.c.method, func.sum(scoped.c.amount)).group_by(scoped.c.method))}
    down = money(s.execute(select(func.coalesce(func.sum(scoped.c.amount),0)).where(scoped.c.kind == 'down_payment')).scalar())
    reversed_count = s.execute(select(func.count()).where(scoped.c.reversal == True)).scalar()
    recent = s.execute(select(scoped).order_by(scoped.c.at.desc()).limit(80)).mappings().all()
    chart_first = max(first, last - __import__('datetime').timedelta(days=29)) if first else last - __import__('datetime').timedelta(days=29)
    chart_start, chart_end = utc_bounds(chart_first, last, zone)
    if s.get_bind().dialect.name == 'postgresql':
        day = func.date(func.timezone(zone, func.timezone('UTC', e.c.at)))
        daily = {k: money(v) for k,v in s.execute(select(day,func.sum(e.c.amount)).where(e.c.at>=chart_start,e.c.at<chart_end).group_by(day))}
    else:
        # Used by isolated SQLite tests only. Production always uses SQL above.
        daily = {}
        for at, amount in s.execute(select(e.c.at,e.c.amount).where(e.c.at>=chart_start,e.c.at<chart_end)):
            day = business_date(at, zone)
            daily[day] = money(daily.get(day, Decimal(0)) + amount)
    return dict(total=total,count=count,average=money(money(gross)/count) if count else Decimal('0.00'),
        methods=methods,down=down,recent=recent,daily=daily,reversed_count=reversed_count)


def attach_payment_totals(s, contracts):
    ids = [c.id for c in contracts]
    if not ids:
        return
    # Chunk IN values to avoid giant parameter lists in PostgreSQL.
    totals = {}
    for offset in range(0,len(ids),500):
        rows = s.execute(select(Payment.contract_id,func.sum(Payment.amount),func.sum(Payment.late_fee_amount))
                .where(Payment.contract_id.in_(ids[offset:offset+500]),Payment.voided_at.is_(None)).group_by(Payment.contract_id))
        totals.update({k:(money(a),money(f)) for k,a,f in rows})
    for c in contracts:
        c._report_payment_totals = totals.get(c.id,(Decimal('0.00'),Decimal('0.00')))


def journal_summary(s, org, first, last, zone):
    lo, hi = utc_bounds(first,last,zone)
    q = select(MoneyEntry.method,func.sum(MoneyEntry.amount)).where(MoneyEntry.organization_id==org,MoneyEntry.occurred_at<hi)
    if lo:
        q=q.where(MoneyEntry.occurred_at>=lo)
    rows = {m:money(v) for m,v in s.execute(q.group_by(MoneyEntry.method))}
    return {'methods':rows,'net':money(sum(rows.values(),Decimal(0)))}
