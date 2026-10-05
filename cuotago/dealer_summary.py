"""Read-only dealer summaries. Historical sales must not use today's cost/price.

These functions deliberately do not write models or infer a purchase payment.
Keeping them independent of Flask also makes the money rules easy to test.
"""
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal('0.00')
CENT = Decimal('0.01')


def amount(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def asset_summary(asset):
    units = max(int(asset.quantity_total or 1), 1)
    work_total = sum((amount(x.amount) for x in asset.investments), ZERO)
    base_unit = amount(asset.estimated_value)
    work_unit = amount(work_total / units)
    cost_unit = amount(base_unit + work_unit)
    target_unit = amount(asset.sale_price)
    target_profit = amount(target_unit - cost_unit) if target_unit > 0 else None
    direct = [x for x in asset.sales if x.status == 'completed']
    financed = [x for x in asset.contracts if x.deal_type == 'credit_sale' and x.status in {'active', 'completed'}]
    return {
        'units': units,
        'purchase_unit': base_unit,
        'investment_unit': work_unit,
        'cost_unit': cost_unit,
        'work_total': amount(work_total),
        'lot_cost': amount(base_unit * units + work_total),
        'target_unit': target_unit,
        'target_profit': target_profit,
        'target_margin': amount(target_profit / cost_unit * 100) if target_profit is not None and cost_unit > 0 else ZERO,
        'direct_count': len(direct),
        'direct_units': sum(max(int(x.quantity or 1), 1) for x in direct),
        'direct_revenue': amount(sum((amount(x.total_amount) for x in direct), ZERO)),
        'direct_cost': amount(sum((amount(x.total_cost) for x in direct), ZERO)),
        'direct_profit': amount(sum((amount(x.profit_amount) for x in direct), ZERO)),
        'agreement_count': len(financed),
        'agreement_revenue': amount(sum((amount(x.total_amount) for x in financed), ZERO)),
        'agreement_received': amount(sum((amount(x.paid_total) for x in financed), ZERO)),
        'agreement_balance': amount(sum((amount(x.balance) for x in financed if x.status == 'active'), ZERO)),
    }


def client_summary(contracts, sales):
    completed = [s for s in sales if s.status == 'completed']
    cash_received = amount(sum((amount(s.total_amount) for s in completed), ZERO))
    # Retained receipts of cancelled agreements are still money received.
    agreement_received = amount(sum((amount(c.paid_total) for c in contracts), ZERO))
    return {
        'cash_count': len(completed),
        'cash_received': cash_received,
        'agreement_received': agreement_received,
        'received_total': amount(cash_received + agreement_received),
        'balance': amount(sum((amount(c.balance) for c in contracts if c.status == 'active'), ZERO)),
        'voided_count': sum(s.status == 'voided' for s in sales),
    }


def csv_cell(value):
    """Prevent spreadsheet formulas in text exports; keep numeric types numeric."""
    if value is None:
        return ''
    if isinstance(value, str) and value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def operational_status(asset):
    """Presentation/read model of stock state; never dirties a SQLAlchemy row."""
    if asset.status in {'maintenance', 'workshop'} and asset.committed_quantity == 0:
        return asset.status
    if asset.available_quantity > 0:
        return 'available'
    if any(c.status == 'active' for c in asset.contracts):
        return 'on_loan'
    sold = any(c.status == 'completed' and c.deal_type == 'credit_sale' for c in asset.contracts)
    sold = sold or any(s.status == 'completed' for s in asset.sales)
    return 'sold' if sold else 'available'
