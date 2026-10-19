"""Money and perpetual-average inventory primitives. No writes or commits here."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal("0.01")
MAX_MONEY = Decimal("9999999999.99")

def money(value):
    try:
        result = Decimal(str(value if value is not None else 0))
        if not result.is_finite() or abs(result) > MAX_MONEY:
            raise ValueError("Monto fuera de rango.")
        return result.quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError):
        raise ValueError("Monto no valido.") from None

def positive_money(value):
    result = money(value)
    if result <= 0:
        raise ValueError("El monto debe ser mayor que cero.")
    return result

def integer(value, minimum=1, maximum=1000000):
    try:
        result = int(str(value))
    except (ValueError, TypeError):
        raise ValueError("Cantidad no valida.") from None
    if result < minimum or result > maximum:
        raise ValueError("Cantidad fuera de rango.")
    return result

def average_cost(on_hand, unit_cost, received, received_cost):
    on_hand = integer(on_hand, 0)
    received = integer(received)
    cost, incoming = money(unit_cost), money(received_cost)
    if cost < 0 or incoming < 0:
        raise ValueError("El costo no puede ser negativo.")
    return money((Decimal(on_hand) * cost + Decimal(received) * incoming) / Decimal(on_hand + received))

def valued_quantity(asset):
    """Exclude sold units, not units temporarily on rental/loan. No historical rewrites."""
    sold = sum(int(s.quantity or 1) for s in asset.sales if s.status == "completed")
    sold += sum(int(c.quantity or 1) for c in asset.contracts
                if not getattr(c, "inventory_released", False) and c.deal_type == "credit_sale" and c.status in {"active", "completed"})
    result = int(asset.quantity_total or 0) - sold
    if result < 0:
        raise ValueError("Inventario inconsistente: revisa unidades vendidas antes de reponer.")
    return result

def receive_stock(asset, quantity, unit_cost):
    quantity = integer(quantity)
    asset.estimated_value = average_cost(valued_quantity(asset), asset.estimated_value, quantity, unit_cost)
    asset.quantity_total = int(asset.quantity_total or 0) + quantity
    return asset.estimated_value

def return_stock_cost(asset, quantity, original_cost):
    """Call BEFORE marking a sale/credit contract void. Total units are historical."""
    asset.estimated_value = average_cost(valued_quantity(asset), asset.estimated_value, quantity, original_cost)
    return asset.estimated_value
