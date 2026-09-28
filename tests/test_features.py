"""SQL feature-layer tests on a small synthetic fixture database.

The fixture spans 2024-03-20 to 2024-04-12: the spring clock change
(2024-03-31), Good Friday (29 Mar, GB-wide) and Easter Monday (1 Apr,
England & Wales only), with a data gap and a suspect value inside it.
"""

import copy
import math
from datetime import date, datetime, timedelta

import pytest

from carbon_forecast.config import load_settings
from carbon_forecast.db import connect, init_raw_schema
from carbon_forecast.features import build_features
from carbon_forecast.ingest.open_meteo import upsert_locations

START, END = datetime(2024, 3, 20), datetime(2024, 4, 12, 23, 30)
# Both inside the 24h window that ends at CUTOFF (2024-04-05 10:30).
GAP = (datetime(2024, 4, 4, 13, 0), datetime(2024, 4, 4, 15, 30))  # 6 missing periods
SUSPECT_AT = datetime(2024, 4, 4, 20, 0)  # actual set to 0 -> must become NULL
ORIGIN = datetime(2024, 4, 5, 12, 0)  # origin used for leak and value checks
LAG = timedelta(minutes=60)
CUTOFF = ORIGIN - timedelta(minutes=30) - LAG


def _settings() -> dict:
    s = copy.deepcopy(load_settings())
    s["start_date"] = START.date()
    return s


def _populate(con, settings, mutate_after: datetime | None = None) -> None:
    """Deterministic synthetic raw data. If `mutate_after` is set, every value that
    would only be published after that origin is changed, so any feature that
    reads it will differ."""
    init_raw_schema(con)
    upsert_locations(con, settings["locations"])
    avail = settings["features"]["weather_forecast_availability_hours"]
    m_cut = mutate_after - timedelta(minutes=30) - LAG if mutate_after else datetime.max
    args = {"s": START, "e": END, "cut": m_cut}
    con.execute(
        """
        INSERT INTO raw_intensity
        SELECT ts, ts + INTERVAL 30 MINUTE,
               v + 7, CASE WHEN ts = $suspect THEN 0 ELSE v END, 'moderate', now()::TIMESTAMP
        FROM (SELECT ts,
                     (100 + (epoch(ts)::BIGINT // 1800) % 97
                      + CASE WHEN ts > $cut THEN 300 ELSE 0 END)::INTEGER AS v
              FROM (SELECT unnest(generate_series($s::TIMESTAMP, $e::TIMESTAMP,
                                                  INTERVAL 30 MINUTE)) AS ts))
        WHERE ts NOT BETWEEN $g0 AND $g1
        """,
        {**args, "suspect": SUSPECT_AT, "g0": GAP[0], "g1": GAP[1]},
    )
    con.execute(
        """
        INSERT INTO raw_generation
        SELECT ts, ts + INTERVAL 30 MINUTE, f.fuel,
               f.base + ((epoch(ts)::BIGINT // 1800) % 11) + CASE WHEN ts > $cut THEN 5 ELSE 0 END,
               now()::TIMESTAMP
        FROM (SELECT unnest(generate_series($s::TIMESTAMP, $e::TIMESTAMP,
                                            INTERVAL 30 MINUTE)) AS ts)
        CROSS JOIN (VALUES ('gas', 30), ('wind', 25), ('solar', 5), ('nuclear', 15),
                           ('imports', 8), ('biomass', 5), ('hydro', 1), ('coal', 0),
                           ('other', 0)) f(fuel, base)
        WHERE ts NOT BETWEEN $g0 AND $g1
        """,
        {**args, "g0": GAP[0], "g1": GAP[1]},
    )
    hourly = """
        SELECT l.location_id, ts,
               5 + (epoch(ts)::BIGINT // 3600) % 13 + l.k AS wind,
               greatest(0, 400 - abs(hour(ts) - 12) * 60) + l.k AS ghi,
               8 + (epoch(ts)::BIGINT // 3600) % 7 AS temp,
               (epoch(ts)::BIGINT // 3600) % 100 AS cloud
        FROM (SELECT unnest(generate_series($s::TIMESTAMP, $e::TIMESTAMP, INTERVAL 1 HOUR)) AS ts)
        CROSS JOIN (SELECT location_id, row_number() OVER (ORDER BY location_id) AS k
                    FROM raw_weather_locations) l
    """
    con.execute(
        f"""
        INSERT INTO raw_weather_archive
        SELECT location_id, ts, wind + CASE WHEN ts > $cut THEN 50 ELSE 0 END, ghi, temp, cloud,
               now()::TIMESTAMP
        FROM ({hourly})
        """,
        args,
    )
    con.execute(
        f"""
        INSERT INTO raw_weather_prev_runs
        SELECT location_id, ts, lead, wind + lead
                   + CASE WHEN ts - to_days(lead) + to_hours($avail) > $origin THEN 50 ELSE 0 END,
               ghi + lead, temp + lead, cloud, now()::TIMESTAMP
        FROM ({hourly}) CROSS JOIN (VALUES (1), (2), (3)) v(lead)
        """,
        {"s": START, "e": END, "avail": avail, "origin": mutate_after or datetime.max},
    )


def _build(mutate_after: datetime | None = None):
    settings = _settings()
    con = connect()
    _populate(con, settings, mutate_after)
    counts = build_features(con, settings)
    return con, settings, counts


@pytest.fixture(scope="module")
def built():
    con, settings, counts = _build()
    yield con, settings, counts
    con.close()


def _rows(con, sql, params=None):
    cur = con.execute(sql, params or {})
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


# --- required checks -------------------------------------------------------


def test_no_input_is_available_after_the_origin(built):
    con, _, _ = built
    asof_cols = [
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'training_set' AND column_name LIKE 'asof_%'"
        ).fetchall()
    ]
    assert len(asof_cols) == 4
    for col in asof_cols:
        bad, nulls = con.execute(
            f"SELECT count(*) FILTER (WHERE {col} > origin_time_utc), "
            f"count(*) FILTER (WHERE {col} IS NULL) FROM training_set"
        ).fetchone()
        assert (bad, nulls) == (0, 0), col


def test_no_duplicate_keys(built):
    con, _, _ = built
    dupes = con.execute(
        "SELECT count(*) FROM (SELECT origin_time_utc, horizon_h FROM training_set "
        "GROUP BY ALL HAVING count(*) > 1)"
    ).fetchone()[0]
    assert dupes == 0
    per_target = con.execute(
        "SELECT count(*) FROM (SELECT origin_time_utc, target_time_utc FROM training_set "
        "GROUP BY ALL HAVING count(*) > 1)"
    ).fetchone()[0]
    assert per_target == 0


def test_expected_row_counts(built):
    con, settings, counts = built
    f = settings["features"]
    spine_end = datetime.combine(END.date(), datetime.min.time()) + timedelta(days=3, minutes=-30)
    origins, t = [], START + timedelta(days=8)
    while t + timedelta(hours=f["horizon_max_h"]) <= spine_end:
        if t.minute == 0 and t.hour in f["origin_hours_utc"]:
            origins.append(t)
        t += timedelta(minutes=30)
    n_horizons = (f["horizon_max_h"] - f["horizon_min_h"]) * 2 + 1
    assert n_horizons == 49
    assert counts["training_set"] == len(origins) * n_horizons
    assert counts["calendar"] == (spine_end - START) // timedelta(minutes=30) + 1
    assert counts["feat_history"] == (END - START) // timedelta(minutes=30) + 1


def test_features_do_not_change_when_future_data_changes(built):
    """Leak canary: corrupt everything published after ORIGIN and rebuild. Every
    f_* and wxf_* value for ORIGIN must be identical; y_ and oracle_ must not."""
    con, _, _ = built
    mutated, _, _ = _build(mutate_after=ORIGIN)
    q = "SELECT * FROM training_set WHERE origin_time_utc = $o ORDER BY horizon_h"
    clean, dirty = _rows(con, q, {"o": ORIGIN}), _rows(mutated, q, {"o": ORIGIN})
    assert len(clean) == len(dirty) == 49
    feature_cols = [c for c in clean[0] if c.startswith(("f_", "wxf_"))]
    assert len(feature_cols) > 30
    for a, b in zip(clean, dirty, strict=True):
        for col in feature_cols:
            assert a[col] == b[col], (a["horizon_h"], col)
    # The mutation really did reach the target period and the observed weather.
    assert all(a["y_actual_gco2"] != b["y_actual_gco2"] for a, b in zip(clean, dirty, strict=True))
    assert all(
        a["oracle_wind_speed_100m_mean"] != b["oracle_wind_speed_100m_mean"]
        for a, b in zip(clean, dirty, strict=True)
    )
    mutated.close()


# --- layer-level checks ----------------------------------------------------


def test_calendar_dst_and_bank_holidays(built):
    con, _, _ = built
    day = {
        r["uk_date"]: r
        for r in _rows(
            con,
            "SELECT uk_date, max(settlement_period) AS max_sp, count(*) AS n, "
            "bool_or(is_bank_holiday_ew) AS ew, bool_or(is_bank_holiday_scot) AS scot, "
            "bool_and(is_dst) AS all_dst, bool_or(is_dst) AS any_dst "
            "FROM calendar GROUP BY uk_date",
        )
    }
    assert (day[date(2024, 3, 31)]["n"], day[date(2024, 3, 31)]["max_sp"]) == (46, 46)
    assert day[date(2024, 3, 30)]["n"] == 48 and not day[date(2024, 3, 30)]["any_dst"]
    assert day[date(2024, 4, 2)]["all_dst"]
    assert day[date(2024, 3, 29)]["ew"] and day[date(2024, 3, 29)]["scot"]  # Good Friday
    assert day[date(2024, 4, 1)]["ew"] and not day[date(2024, 4, 1)]["scot"]  # Easter Monday
    assert not day[date(2024, 4, 3)]["ew"]
    # BST local midnight on 2 April is 23:00 UTC on 1 April.
    sp1 = con.execute(
        "SELECT period_start_utc FROM calendar WHERE uk_date = DATE '2024-04-02' "
        "AND settlement_period = 1"
    ).fetchone()[0]
    assert sp1 == datetime(2024, 4, 1, 23, 0)


def test_staging_nulls_suspect_values(built):
    con, _, _ = built
    actual, flagged = con.execute(
        "SELECT actual_gco2, actual_is_suspect FROM stg_intensity WHERE period_start_utc = $t",
        {"t": SUSPECT_AT},
    ).fetchone()
    assert actual is None and flagged


def test_history_features_match_python(built):
    con, _, _ = built
    actual = dict(con.execute("SELECT period_start_utc, actual_gco2 FROM stg_intensity").fetchall())
    row = _rows(
        con,
        "SELECT * FROM training_set WHERE origin_time_utc = $o AND horizon_h = 24",
        {"o": ORIGIN},
    )[0]
    half = timedelta(minutes=30)
    assert row["f_intensity_latest"] == actual[CUTOFF]
    assert row["f_intensity_latest_minus_24h"] == actual[CUTOFF - timedelta(hours=24)]
    assert row["f_intensity_latest_minus_168h"] == actual[CUTOFF - timedelta(hours=168)]
    # 24h window ending at the cutoff contains the gap and the suspect value.
    window = [actual.get(CUTOFF - i * half) for i in range(48)]
    known = [v for v in window if v is not None]
    assert len(known) == 48 - 6 - 1
    assert row["f_intensity_obs_24h"] == len(known)
    assert row["f_intensity_mean_24h"] == pytest.approx(sum(known) / len(known))
    mean = sum(known) / len(known)
    std = math.sqrt(sum((v - mean) ** 2 for v in known) / (len(known) - 1))
    assert row["f_intensity_std_24h"] == pytest.approx(std)


def test_seasonal_lags_use_the_latest_published_day(built):
    con, _, _ = built
    actual = dict(con.execute("SELECT period_start_utc, actual_gco2 FROM stg_intensity").fetchall())
    for r in _rows(
        con,
        "SELECT horizon_h, target_time_utc, f_seasonal_lag_days, "
        "f_intensity_target_seasonal_day, f_intensity_target_minus_168h "
        "FROM training_set WHERE origin_time_utc = $o",
        {"o": ORIGIN},
    ):
        expected_days = 2 if r["horizon_h"] <= 46.5 else 3
        assert r["f_seasonal_lag_days"] == expected_days, r["horizon_h"]
        src = r["target_time_utc"] - timedelta(days=expected_days)
        assert src + timedelta(minutes=30) + LAG <= ORIGIN
        assert r["f_intensity_target_seasonal_day"] == actual.get(src)
        assert r["f_intensity_target_minus_168h"] == actual.get(
            r["target_time_utc"] - timedelta(hours=168)
        )


def test_weather_alignment_to_half_hours(built):
    con, _, _ = built
    raw = {
        (loc, t): (wind, ghi)
        for loc, t, wind, ghi in con.execute(
            "SELECT location_id, time_utc, wind_speed_100m, shortwave_radiation "
            "FROM raw_weather_archive"
        ).fetchall()
    }
    roles = dict(con.execute("SELECT location_id, role FROM raw_weather_locations").fetchall())
    wind_sites = [loc for loc, r in roles.items() if r == "wind"]
    solar_sites = [loc for loc, r in roles.items() if r == "solar"]
    h0 = datetime(2024, 4, 3, 10, 0)
    h1 = h0 + timedelta(hours=1)
    for period, w1 in ((h0, 0.25), (h0 + timedelta(minutes=30), 0.75)):
        wind, ghi = con.execute(
            "SELECT wind_speed_100m_mean, solar_radiation_mean FROM feat_weather "
            "WHERE period_start_utc = $p AND lead_days = 0",
            {"p": period},
        ).fetchone()
        exp_wind = sum((1 - w1) * raw[s, h0][0] + w1 * raw[s, h1][0] for s in wind_sites)
        assert wind == pytest.approx(exp_wind / len(wind_sites))
        # radiation is a preceding-hour mean: the value stamped h1 covers [h0, h1)
        assert ghi == pytest.approx(sum(raw[s, h1][1] for s in solar_sites) / len(solar_sites))


def test_weather_forecast_lead_day_depends_on_horizon(built):
    con, _, _ = built
    # Chosen from the later hourly input (h0 + 1h): day 2 up to 39.5h, then day 3.
    for horizon, lead in ((24.0, 2), (39.0, 2), (39.5, 2), (40.0, 3), (48.0, 3)):
        target, wxf = con.execute(
            "SELECT target_time_utc, wxf_demand_temperature FROM training_set "
            "WHERE origin_time_utc = $o AND horizon_h = $h",
            {"o": ORIGIN, "h": horizon},
        ).fetchone()
        exp = con.execute(
            "SELECT demand_temperature FROM feat_weather "
            "WHERE period_start_utc = $t AND lead_days = $l",
            {"t": target, "l": lead},
        ).fetchone()[0]
        assert wxf == pytest.approx(exp), horizon


def test_weather_averages_have_a_fixed_summation_order():
    """A parallel avg() sums in thread order, so its last bits vary between builds
    and LightGBM splits can change. Every avg() in the weather join must be ordered
    (a real build differed in ~42k feat_weather rows before this was fixed)."""
    import re

    from carbon_forecast.config import SQL_DIR

    sql = re.sub(r"--[^\n]*", "", (SQL_DIR / "04_weather_join.sql").read_text())  # drop comments
    calls = re.findall(r"avg\(([^)]*)\)", sql)
    assert calls, "expected avg() aggregates in 04_weather_join.sql"
    assert all("ORDER BY" in c for c in calls), calls
