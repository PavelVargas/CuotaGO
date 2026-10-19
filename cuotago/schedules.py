"""Explicit frequencies. Legacy biweekly remains 14 days, never relabelled as 15."""
import calendar
from datetime import date, timedelta

FREQUENCIES = {'weekly', 'biweekly', 'every15', 'semi_monthly', 'monthly'}
LABELS = {'weekly': 'Semanal (7 dias)', 'biweekly': 'Cada 14 dias',
          'every15': 'Cada 15 dias', 'semi_monthly': 'Dia 15 y fin de mes', 'monthly': 'Mensual'}


def add_months(day, months):
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def due_dates(first, frequency, count):
    if frequency not in FREQUENCIES or count < 1 or count > 500:
        raise ValueError('Frecuencia o cantidad de cuotas no valida.')
    if frequency == 'semi_monthly' and first.day not in {15, calendar.monthrange(first.year, first.month)[1]}:
        raise ValueError('Para 15 y fin de mes, la primera cuota debe ser el 15 o el ultimo dia del mes.')
    current = first
    for index in range(count):
        if frequency == 'monthly':
            current = add_months(first, index)
        elif frequency in {'weekly', 'biweekly', 'every15'}:
            current = first + timedelta(days=index * {'weekly': 7, 'biweekly': 14, 'every15': 15}[frequency])
        elif index:
            last = calendar.monthrange(current.year, current.month)[1]
            current = current.replace(day=last) if current.day == 15 else add_months(current.replace(day=15), 1)
        yield current
