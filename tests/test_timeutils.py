from datetime import date, datetime, timedelta

import pytest

from carbon_forecast.quality import dst_check
from carbon_forecast.timeutils import (
    PERIOD,
    periods_in_uk_day,
    settlement_period,
    uk_day_bounds_utc,
)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2019, 3, 31), 46),  # clocks forward
        (date(2019, 10, 27), 50),  # clocks back
        (date(2019, 6, 1), 48),
        (date(2019, 12, 1), 48),
        (date(2026, 3, 29), 46),
        (date(2026, 10, 25), 50),
    ],
)
def test_periods_in_uk_day(day, expected):
    assert periods_in_uk_day(day) == expected


def test_uk_day_bounds_on_transition_days():
    # Spring: local midnight is GMT, next midnight is BST -> day ends 23:00 UTC.
    assert uk_day_bounds_utc(date(2019, 3, 31)) == (
        datetime(2019, 3, 31, 0, 0),
        datetime(2019, 3, 31, 23, 0),
    )
    # Autumn: starts at 23:00 UTC the previous evening, ends at midnight UTC.
    assert uk_day_bounds_utc(date(2019, 10, 27)) == (
        datetime(2019, 10, 26, 23, 0),
        datetime(2019, 10, 28, 0, 0),
    )


def test_settlement_period_edges():
    assert settlement_period(datetime(2019, 3, 31, 0, 0)) == (date(2019, 3, 31), 1)
    assert settlement_period(datetime(2019, 3, 31, 22, 30)) == (date(2019, 3, 31), 46)
    assert settlement_period(datetime(2019, 3, 31, 23, 0)) == (date(2019, 4, 1), 1)
    assert settlement_period(datetime(2019, 10, 26, 23, 0)) == (date(2019, 10, 27), 1)
    assert settlement_period(datetime(2019, 10, 27, 23, 30)) == (date(2019, 10, 27), 50)
    # The repeated local hour 01:00-02:00 maps to distinct periods.
    assert settlement_period(datetime(2019, 10, 27, 0, 0))[1] == 3
    assert settlement_period(datetime(2019, 10, 27, 1, 0))[1] == 5


def test_every_day_2019_2026_has_contiguous_settlement_periods():
    day = date(2019, 1, 1)
    while day <= date(2026, 12, 31):
        start, end = uk_day_bounds_utc(day)
        n = (end - start) // PERIOD
        assert n in (46, 48, 50)
        sps = [settlement_period(start + i * PERIOD) for i in range(n)]
        assert sps == [(day, i + 1) for i in range(n)], day
        day += timedelta(days=1)


def test_sql_dst_check_agrees_with_python_on_gap_free_utc_grid(con):
    # A complete UTC half-hour grid must produce 46/48/50 periods per UK day,
    # exactly as the Python calendar says, with no mismatches.
    con.execute("""
        INSERT INTO raw_intensity
        SELECT ts, ts + INTERVAL 30 MINUTE, 100, 100, 'low', now()::TIMESTAMP
        FROM (SELECT unnest(generate_series(TIMESTAMP '2019-01-01', TIMESTAMP '2026-12-31 23:30',
                                            INTERVAL 30 MINUTE)) AS ts)
    """)
    rows = dst_check(con, datetime(2019, 1, 1))
    assert len(rows) > 2900
    for uk_date, stored, expected in rows:
        assert stored == expected == periods_in_uk_day(uk_date), uk_date
    assert sorted({e for _, _, e in rows}) == [46, 48, 50]
