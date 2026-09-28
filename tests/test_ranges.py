from datetime import datetime, timedelta

from carbon_forecast.ingest.ranges import missing_ranges, plan_chunks

HALF = timedelta(minutes=30)
PRESENT = "SELECT period_start_utc AS ts FROM raw_intensity"


def _insert(con, start, end):
    con.execute(
        """INSERT INTO raw_intensity
           SELECT ts, ts + INTERVAL 30 MINUTE, 1, 1, 'low', now()::TIMESTAMP
           FROM (SELECT unnest(generate_series($s::TIMESTAMP, $e::TIMESTAMP,
                                               INTERVAL 30 MINUTE)) AS ts)""",
        {"s": start, "e": end},
    )


def test_empty_table_is_one_missing_range(con):
    s, e = datetime(2020, 1, 1), datetime(2020, 1, 31, 23, 30)
    assert missing_ranges(con, PRESENT, s, e, HALF) == [(s, e)]


def test_holes_become_islands(con):
    _insert(con, datetime(2020, 1, 1), datetime(2020, 1, 1, 9, 30))
    _insert(con, datetime(2020, 1, 1, 11, 0), datetime(2020, 1, 1, 20, 0))
    got = missing_ranges(con, PRESENT, datetime(2020, 1, 1), datetime(2020, 1, 1, 23, 30), HALF)
    assert got == [
        (datetime(2020, 1, 1, 10, 0), datetime(2020, 1, 1, 10, 30)),
        (datetime(2020, 1, 1, 20, 30), datetime(2020, 1, 1, 23, 30)),
    ]


def test_fully_present_means_nothing_missing(con):
    _insert(con, datetime(2020, 1, 1), datetime(2020, 1, 2))
    assert missing_ranges(con, PRESENT, datetime(2020, 1, 1), datetime(2020, 1, 2), HALF) == []


def test_long_range_is_split_within_max_span_and_covers_everything():
    s, e = datetime(2019, 1, 1), datetime(2019, 4, 10, 23, 30)
    max_span = timedelta(days=30)
    chunks = plan_chunks([(s, e)], HALF, max_span)
    assert chunks[0][0] == s and chunks[-1][1] == e
    for (_, b), (c, _) in zip(chunks, chunks[1:], strict=False):
        assert c == b + HALF  # contiguous, no overlap, no gap
    assert all(b + HALF - a <= max_span for a, b in chunks)
    assert len(chunks) == 4  # 100 days -> 30 + 30 + 30 + 10


def test_nearby_islands_merge_distant_ones_do_not():
    day = timedelta(days=1)
    t0 = datetime(2020, 1, 1)
    ranges = [(t0, t0 + HALF), (t0 + 2 * day, t0 + 2 * day), (t0 + 90 * day, t0 + 90 * day)]
    chunks = plan_chunks(ranges, HALF, timedelta(days=30))
    assert chunks == [(t0, t0 + 2 * day), (t0 + 90 * day, t0 + 90 * day)]
