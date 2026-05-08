from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def now_in_shanghai() -> datetime:
    """Return an aware datetime in Asia/Shanghai."""
    return datetime.now(SHANGHAI_TZ)


def now_in_utc_naive() -> datetime:
    """Return a naive UTC datetime for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_shanghai_datetime(value: datetime | None) -> datetime:
    """Normalize a datetime to Asia/Shanghai.

    The project historically stored some naive timestamps. We treat naive
    timestamps as UTC on read and convert them to Shanghai for presentation.
    """
    if value is None:
        return now_in_shanghai()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).astimezone(SHANGHAI_TZ)
    return value.astimezone(SHANGHAI_TZ)


def serialize_shanghai_datetime(value: datetime) -> str:
    """Serialize a datetime as an ISO-8601 string in Asia/Shanghai."""
    return ensure_shanghai_datetime(value).isoformat()
