"""Business dates; persisted event timestamps remain naive UTC for compatibility."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_ZONE = "America/Santo_Domingo"

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def business_datetime(value, zone=DEFAULT_ZONE):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(zone))

def business_date(value, zone=DEFAULT_ZONE):
    return business_datetime(value, zone).date() if isinstance(value, datetime) else value

def utc_bounds(first, last, zone=DEFAULT_ZONE):
    """Inclusive local dates -> [start, end) UTC, also valid over DST changes."""
    if last is None or (first is not None and first > last):
        raise ValueError("Rango de fechas no valido.")
    tz = ZoneInfo(zone)
    start = datetime.combine(first, time.min, tz).astimezone(timezone.utc).replace(tzinfo=None) if first else None
    end = datetime.combine(last + timedelta(days=1), time.min, tz).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end
