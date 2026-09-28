"""UK settlement-period helpers.

GB settlement periods are numbered from local (Europe/London) midnight, so a
UK day has 48 periods normally, 46 on the spring-forward Sunday and 50 on the
autumn-back Sunday. Data is stored in UTC; these functions map between the two.
The SQL layer uses DuckDB's ICU timezone functions for the same mapping, and
the tests check the two implementations agree.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
PERIOD = timedelta(minutes=30)


def uk_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """UTC instants (naive) of local midnight at the start and end of a UK day."""
    start = datetime(day.year, day.month, day.day, tzinfo=UK)
    end = start + timedelta(days=1)  # aware arithmetic is wall-clock in the local zone
    return (
        start.astimezone(UTC).replace(tzinfo=None),
        end.astimezone(UTC).replace(tzinfo=None),
    )


def periods_in_uk_day(day: date) -> int:
    start, end = uk_day_bounds_utc(day)
    return (end - start) // PERIOD


def settlement_period(period_start_utc: datetime) -> tuple[date, int]:
    """(UK local date, settlement period 1..50) for a naive-UTC period start."""
    local_day = period_start_utc.replace(tzinfo=UTC).astimezone(UK).date()
    day_start, _ = uk_day_bounds_utc(local_day)
    return local_day, (period_start_utc - day_start) // PERIOD + 1
