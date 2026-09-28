import copy
import re
from datetime import datetime, timedelta

from carbon_forecast.ingest import carbon_intensity as ci
from tests.conftest import load_fixture

NOW = datetime(2026, 1, 1)


class FakeCarbonAPI:
    """Emulates the verified API semantics: returns every half-hour whose END
    falls in [from, to], and rejects ranges over 31 days."""

    def __init__(self, null_actual_after: datetime | None = None):
        self.null_actual_after = null_actual_after
        self.calls: list[tuple[datetime, datetime]] = []

    def get_json(self, url, params=None):
        f, t = (
            datetime.strptime(x, ci.API_TS) for x in re.search(r"/([^/]+Z)/([^/]+Z)$", url).groups()
        )
        assert t - f <= timedelta(days=31), "API would reject this range"
        self.calls.append((f, t))
        rows, end = [], f
        while end <= t:
            start = end - ci.STEP
            actual = None if self.null_actual_after and start >= self.null_actual_after else 200
            rows.append(
                {
                    "from": start.strftime(ci.API_TS),
                    "to": end.strftime(ci.API_TS),
                    "intensity": {"forecast": 190, "actual": actual, "index": "moderate"},
                }
            )
            end += ci.STEP
        return {"data": rows}


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

    # Extending the window only fetches the new tail.
    ci.ingest(con, api, "intensity", "https://x", start, end + timedelta(days=2), max_days=30)
    assert api.calls[-1] == (end + ci.STEP, end + timedelta(days=2) + ci.STEP)


def test_unsettled_periods_are_refetched(con):
    start, end = datetime(2020, 1, 1), datetime(2020, 1, 2, 23, 30)
    api = FakeCarbonAPI(null_actual_after=datetime(2020, 1, 2, 12))
    ci.ingest(con, api, "intensity", "https://x", start, end, max_days=30)
    api.null_actual_after = None
    ci.ingest(con, api, "intensity", "https://x", start, end, max_days=30)
    assert api.calls[-1][0] == datetime(2020, 1, 2, 12)
    assert (
        con.execute("SELECT count(*) FROM raw_intensity WHERE actual_gco2 IS NULL").fetchone()[0]
        == 0
    )
