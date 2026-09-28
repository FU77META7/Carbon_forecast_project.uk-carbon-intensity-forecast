import copy
import re
from datetime import UTC, datetime, timedelta

from carbon_forecast.ingest import carbon_intensity as ci
from tests.conftest import load_fixture

NOW = datetime(2026, 1, 1)


class FakeCarbonAPI:
    """Emulates the verified API behaviour: returns every half-hour whose END
    falls in [from, to], rejects ranges over 31 days, and /generation drops
    everything after 31 Dec when from/to straddle a year boundary."""

    def __init__(self, null_actual_after: datetime | None = None):
        self.null_actual_after = null_actual_after
        self.calls: list[tuple[datetime, datetime]] = []

    def get_json(self, url, params=None):
        path, f, t = re.search(r"/(\w+)/([^/]+Z)/([^/]+Z)$", url).groups()
        f, t = datetime.strptime(f, ci.API_TS), datetime.strptime(t, ci.API_TS)
        assert t - f <= timedelta(days=31), "API would reject this range"
        self.calls.append((f, t))
        if path == "generation" and f.year != t.year:
            t = datetime(f.year, 12, 31, 23, 30)
        rows, end = [], f
        while end <= t:
            row = {"from": (end - ci.STEP).strftime(ci.API_TS), "to": end.strftime(ci.API_TS)}
            if path == "generation":
                row["generationmix"] = [
                    {"fuel": "gas", "perc": 40.0},
                    {"fuel": "wind", "perc": 60.0},
                ]
            else:
                unsettled = self.null_actual_after and end - ci.STEP >= self.null_actual_after
                row["intensity"] = {
                    "forecast": 190,
                    "actual": None if unsettled else 200,
                    "index": "moderate",
                }
            rows.append(row)
            end += ci.STEP
        return {"data": rows}


def test_split_at_year_end_keeps_request_ends_within_one_year():
    s, e = datetime(2019, 12, 27), datetime(2020, 1, 25, 23, 30)
    chunks = ci.split_at_year_end([(s, e)])
    assert chunks == [(s, datetime(2019, 12, 31, 23, 0)), (datetime(2019, 12, 31, 23, 30), e)]
    assert all((a + ci.STEP).year == (b + ci.STEP).year for a, b in chunks)


def test_load_intensity_fixture_is_idempotent(con):
    payload = load_fixture("intensity_sample.json")
    assert ci.load_intensity(con, payload, NOW) == 7
    assert ci.load_intensity(con, payload, NOW) == 7  # updates, no new rows
    assert con.execute("SELECT count(*) FROM raw_intensity").fetchone()[0] == 7
    first = con.execute(
        "SELECT period_start_utc, period_end_utc, forecast_gco2, actual_gco2 FROM raw_intensity "
        "ORDER BY 1 LIMIT 1"
    ).fetchone()
    raw = payload["data"][0]
    assert first == (
        datetime(2024, 10, 26, 22, 30),
        datetime(2024, 10, 26, 23, 0),
        raw["intensity"]["forecast"],
        raw["intensity"]["actual"],
    )


def test_null_never_overwrites_a_known_value_but_revisions_do(con):
    payload = load_fixture("intensity_sample.json")
    ci.load_intensity(con, payload, NOW)
    nulled = copy.deepcopy(payload)
    for r in nulled["data"]:
        r["intensity"]["actual"] = None
    ci.load_intensity(con, nulled, NOW)
    assert (
        con.execute("SELECT count(*) FROM raw_intensity WHERE actual_gco2 IS NULL").fetchone()[0]
        == 0
    )
    revised = copy.deepcopy(payload)
    revised["data"][0]["intensity"]["actual"] = 999
    ci.load_intensity(con, revised, NOW)
    assert con.execute("SELECT max(actual_gco2) FROM raw_intensity").fetchone()[0] == 999


def test_load_generation_fixture_long_format(con):
    payload = load_fixture("generation_sample.json")
    assert ci.load_generation(con, payload, NOW) == 7 * 9
    ci.load_generation(con, payload, NOW)
    n, periods, fuels = con.execute(
        "SELECT count(*), count(DISTINCT period_start_utc), count(DISTINCT fuel) "
        "FROM raw_generation"
    ).fetchone()
    assert (n, periods, fuels) == (63, 7, 9)


def test_incremental_ingest_fetches_only_missing(con):
    api = FakeCarbonAPI()
    start, end = datetime(2019, 1, 1), datetime(2019, 4, 30, 23, 30)
    ci.ingest(con, api, "intensity", "https://x", start, end, max_days=30)
    first_calls = len(api.calls)
    assert first_calls == 4  # 120 days in 30-day chunks
    expected = (end - start) // ci.STEP + 1
    n = con.execute(
        "SELECT count(*) FROM raw_intensity WHERE period_start_utc >= $s", {"s": start}
    ).fetchone()[0]
    assert n == expected  # every slot, across the 2019-03-31 DST change, no duplicates

    ci.ingest(con, api, "intensity", "https://x", start, end, max_days=30)
    assert len(api.calls) == first_calls  # nothing missing -> no requests

    # Extending the window only fetches the new tail (from/to are slot END times).
    ci.ingest(con, api, "intensity", "https://x", start, end + timedelta(days=2), max_days=30)
    assert api.calls[-1] == (end + 2 * ci.STEP, end + timedelta(days=2) + ci.STEP)


def test_generation_across_new_year_is_complete(con):
    api = FakeCarbonAPI()
    start, end = datetime(2019, 12, 10), datetime(2020, 1, 20, 23, 30)
    ci.ingest(con, api, "generation", "https://x", start, end, max_days=30)
    n = con.execute("SELECT count(DISTINCT period_start_utc) FROM raw_generation").fetchone()[0]
    assert n == (end - start) // ci.STEP + 1
    assert all(f.year == t.year for f, t in api.calls)


def test_recent_unsettled_periods_are_refetched(con):
    today = datetime.now(UTC).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    start, end = today - timedelta(days=1), today - ci.STEP
    api = FakeCarbonAPI(null_actual_after=start + timedelta(hours=12))
    ci.ingest(con, api, "intensity", "https://x", start, end, max_days=30)
    api.null_actual_after = None
    ci.ingest(con, api, "intensity", "https://x", start, end, max_days=30)
    assert api.calls[-1][0] == start + timedelta(hours=12, minutes=30)
    nulls = "SELECT count(*) FROM raw_intensity WHERE actual_gco2 IS NULL"
    assert con.execute(nulls).fetchone()[0] == 0


def test_old_upstream_nulls_are_not_refetched_every_run(con):
    # Fetched long after the periods ended -> a null actual is an upstream gap.
    start, end = datetime(2020, 1, 1), datetime(2020, 1, 2, 23, 30)
    api = FakeCarbonAPI(null_actual_after=datetime(2020, 1, 2, 12))
    ci.ingest(con, api, "intensity", "https://x", start, end, max_days=30)
    ci.ingest(con, api, "intensity", "https://x", start, end, max_days=30)
    assert len(api.calls) == 1
