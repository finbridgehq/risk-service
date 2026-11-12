"""The calendar the business runs on: Lima's.

A certificate is in force "today" in Peru, not in UTC: from 7 p.m. in Lima
the UTC date is already tomorrow. Peru has had no daylight saving time since
1994, so a fixed offset is enough and no time-zone database is needed.
"""
from datetime import UTC, date, datetime, timedelta, timezone

LIMA = timezone(timedelta(hours=-5), "America/Lima")


def lima_date(moment: datetime) -> date:
    """Return the date in Lima at an instant.

    Args:
        moment (datetime): An aware instant.

    Returns:
        date: The day it is in Lima.
    """
    return moment.astimezone(LIMA).date()


def lima_today() -> date:
    """Return today's date in Lima."""
    return lima_date(datetime.now(UTC))
