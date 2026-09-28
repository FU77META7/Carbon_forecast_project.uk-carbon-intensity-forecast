import copy
from datetime import date, datetime, timedelta

from carbon_forecast.ingest import open_meteo as om
from tests.conftest import load_fixture

NOW = datetime(2026, 1, 1)
LOC = {"id": "hornsea", "name": "Hornsea", "role": "wind", "latitude": 53.885, "longitude": 1.791}
SETTINGS = {
    "archive_url": "https://archive",
    "hist_forecast_url": "https://hist",
    "prev_runs_url": "https://prev",
    "prev_runs_model": "ecmwf_ifs025",
    "prev_runs_lead_days": [1, 2, 3],
    "max_days_per_request": 366,
}


def test_archive_fixture_loads_and_is_idempotent(con):
    payload = load_fixture("open_meteo_archive_sample.json")
    assert om.load_single_run(con, "raw_weather_archive", "hornsea", payload, NOW) == 24
    om.load_single_run(con, "raw_weather_archive", "hornsea", payload, NOW)
    row = con.execute(
        "SELECT count(*), min(time_utc), max(time_utc), "
        "any_value(wind_speed_100m) IS NOT NULL FROM raw_weather_archive"
    ).fetchone()
    assert row == (24, datetime(2024, 10, 27, 0), datetime(2024, 10, 27, 23), True)


def test_all_null_hours_are_skipped(con):
    payload = copy.deepcopy(load_fixture("open_meteo_archive_sample.json"))
    for v in om.VARIABLES:
        payload["hourly"][v][-3:] = [None] * 3
    assert om.load_single_run(con, "raw_weather_archive", "hornsea", payload, NOW) == 21


def test_prev_runs_unpivots_lead_days(con):
    payload = load_fixture("open_meteo_prev_runs_sample.json")
    assert om.load_prev_runs(con, "hornsea", payload, [1, 2, 3], NOW) == 72
    om.load_prev_runs(con, "hornsea", payload, [1, 2, 3], NOW)
    by_lead = con.execute(
        "SELECT lead_days, count(*) FROM raw_weather_prev_runs GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert by_lead == [(1, 24), (2, 24), (3, 24)]
    # Stored value for lead 2 at 12:00 equals the API's _previous_day2 value.
    i = payload["hourly"]["time"].index("2024-10-27T12:00")
    got = con.execute(
        "SELECT wind_speed_100m FROM raw_weather_prev_runs WHERE lead_days = 2 "
        "AND time_utc = TIMESTAMP '2024-10-27 12:00'"
    ).fetchone()[0]
    assert got == payload["hourly"]["wind_speed_100m_previous_day2"][i]


class FakeOpenMeteo:
    def __init__(self, lead_days=(1, 2, 3)):
        self.lead_days = lead_days
        self.calls = []

    def get_json(self, url, params):
        self.calls.append((url, params["start_date"], params["end_date"]))
        s, e = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
        hours = [
            datetime.combine(s, datetime.min.time()) + timedelta(hours=i)
            for i in range(((e - s).days + 1) * 24)
        ]
        hourly = {"time": [h.strftime(om.API_TS) for h in hours]}
        for key in params["hourly"].split(","):
            hourly[key] = [1.0] * len(hours)
        return {"hourly": hourly}


def test_incremental_prev_runs_needs_every_lead_day(con):
    api = FakeOpenMeteo()
    start, end = datetime(2024, 3, 9), datetime(2024, 3, 12, 23)
    om.ingest(con, api, "weather_prev_runs", SETTINGS, [LOC], start, end)
    assert len(api.calls) == 1 and api.calls[0][0] == "https://prev"
    assert con.execute("SELECT count(*) FROM raw_weather_prev_runs").fetchone()[0] == 4 * 24 * 3
    om.ingest(con, api, "weather_prev_runs", SETTINGS, [LOC], start, end)
    assert len(api.calls) == 1

    # Losing one lead day for one hour makes that hour missing again.
    con.execute(
        "DELETE FROM raw_weather_prev_runs WHERE lead_days = 3 "
        "AND time_utc = TIMESTAMP '2024-03-11 05:00'"
    )
    om.ingest(con, api, "weather_prev_runs", SETTINGS, [LOC], start, end)
    assert api.calls[-1][1:] == ("2024-03-11", "2024-03-11")


def test_archive_ingest_splits_long_ranges(con):
    api = FakeOpenMeteo()
    om.ingest(
        con,
        api,
        "weather_archive",
        SETTINGS,
        [LOC],
        datetime(2019, 1, 1),
        datetime(2020, 12, 31, 23),
    )
    assert [c[1:] for c in api.calls] == [
        ("2019-01-01", "2020-01-01"),
        ("2020-01-02", "2020-12-31"),
    ]
    assert con.execute("SELECT count(*) FROM raw_weather_archive").fetchone()[0] == 731 * 24
