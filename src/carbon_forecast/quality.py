"""Data quality report for the raw_* tables.

python -m carbon_forecast.quality  -> prints and writes reports/data_quality.md
"""

import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import duckdb

from carbon_forecast.config import REPORTS_DIR, load_settings, resolve
from carbon_forecast.db import connect
from carbon_forecast.ingest.open_meteo import VARIABLES
from carbon_forecast.ingest.ranges import missing_ranges
from carbon_forecast.reporting import markdown_table as _table


@dataclass(frozen=True)
class Series:
    """One regular time series: a table, optionally filtered to a location."""

    label: str
    table: str
    ts_col: str
    step: timedelta
    keys: tuple[str, ...]
    value_cols: tuple[str, ...]
    start: datetime
    where: str = "TRUE"


def _series(con: duckdb.DuckDBPyConnection, settings: dict) -> list[Series]:
    start = datetime.combine(settings["start_date"], datetime.min.time())
    prev_start = datetime.combine(
        settings["open_meteo"]["prev_runs_start_date"], datetime.min.time()
    )
    half, hour = timedelta(minutes=30), timedelta(hours=1)
    out = [
        Series(
            "intensity",
            "raw_intensity",
            "period_start_utc",
            half,
            ("period_start_utc",),
            ("forecast_gco2", "actual_gco2", "intensity_index"),
            start,
        ),
        Series(
            "generation",
            "raw_generation",
            "period_start_utc",
            half,
            ("period_start_utc", "fuel"),
            ("perc",),
            start,
        ),
    ]
    locations = [
        r[0]
        for r in con.execute(
            "SELECT location_id FROM raw_weather_locations ORDER BY location_id"
        ).fetchall()
    ]
    for table, short in (
        ("raw_weather_archive", "archive"),
        ("raw_weather_hist_forecast", "hist_forecast"),
    ):
        out += [
            Series(
                f"{short}/{loc}",
                table,
                "time_utc",
                hour,
                ("location_id", "time_utc"),
                VARIABLES,
                start,
                f"location_id = '{loc}'",
            )
            for loc in locations
        ]
    for lead in settings["open_meteo"]["prev_runs_lead_days"]:
        out += [
            Series(
                f"prev_runs_d{lead}/{loc}",
                "raw_weather_prev_runs",
                "time_utc",
                hour,
                ("location_id", "time_utc", "lead_days"),
                VARIABLES,
                prev_start,
                f"location_id = '{loc}' AND lead_days = {lead}",
            )
            for loc in locations
        ]
    return out


def series_summary(con: duckdb.DuckDBPyConnection, s: Series) -> dict:
    n_rows, first, last = con.execute(
        f"SELECT count(*), min({s.ts_col}), max({s.ts_col}) FROM {s.table} "
        f"WHERE {s.where} AND {s.ts_col} >= $start",
        {"start": s.start},
    ).fetchone()
    keys = ", ".join(s.keys)
    dupes = con.execute(
        f"SELECT count(*) FROM (SELECT {keys} FROM {s.table} WHERE {s.where} "
        f"GROUP BY {keys} HAVING count(*) > 1)"
    ).fetchone()[0]
    nulls = con.execute(
        "SELECT "
        + ", ".join(f"count(*) FILTER (WHERE {c} IS NULL)" for c in s.value_cols)
        + f" FROM {s.table} WHERE {s.where} AND {s.ts_col} >= $start",
        {"start": s.start},
    ).fetchone()
    gaps: list[tuple[datetime, datetime]] = []
    expected = 0
    if last is not None:
        expected = (last - s.start) // s.step + 1
        present = f"SELECT DISTINCT {s.ts_col} AS ts FROM {s.table} WHERE {s.where}"
        gaps = missing_ranges(con, present, s.start, last, s.step)
    distinct_ts = con.execute(
        f"SELECT count(DISTINCT {s.ts_col}) FROM {s.table} "
        f"WHERE {s.where} AND {s.ts_col} >= $start",
        {"start": s.start},
    ).fetchone()[0]
    return {
        "series": s,
        "rows": n_rows,
        "first": first,
        "last": last,
        "expected": expected,
        "distinct_ts": distinct_ts,
        "missing": expected - distinct_ts if last else 0,
        "gaps": gaps,
        "dupes": dupes,
        "nulls": dict(zip(s.value_cols, nulls, strict=True)),
    }


# Periods per UK local date vs the number the calendar says it should have
# (46 / 48 / 50), both computed with DuckDB's ICU timezone support.
DST_SQL = """
WITH local AS (
    SELECT CAST(timezone('Europe/London', period_start_utc AT TIME ZONE 'UTC') AS DATE) AS uk_date
    FROM raw_intensity
    WHERE period_start_utc >= $start
),
per_day AS (
    SELECT uk_date, count(*) AS n_periods FROM local GROUP BY uk_date
)
SELECT
    uk_date,
    n_periods,
    CAST((epoch(timezone('Europe/London', (uk_date + 1)::TIMESTAMP))
          - epoch(timezone('Europe/London', uk_date::TIMESTAMP))) / 1800 AS INTEGER) AS expected
FROM per_day
WHERE uk_date > (SELECT min(uk_date) FROM per_day)   -- first/last local day are partial
  AND uk_date < (SELECT max(uk_date) FROM per_day)
ORDER BY uk_date
"""


def dst_check(con: duckdb.DuckDBPyConnection, start: datetime) -> list[tuple[date, int, int]]:
    return con.execute(DST_SQL, {"start": start}).fetchall()


def build_report(con: duckdb.DuckDBPyConnection, settings: dict) -> str:
    start = datetime.combine(settings["start_date"], datetime.min.time())
    summaries = [series_summary(con, s) for s in _series(con, settings)]
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        "# Data quality report",
        "",
        f"Generated {now} by `python -m carbon_forecast.quality`. All timestamps are UTC.",
        "Expected slots run from the configured start of each series to its latest stored "
        "timestamp, on a 30-minute (Carbon Intensity) or hourly (weather) grid.",
        "",
        "## Coverage, gaps, duplicates and nulls",
        "",
    ]
    rows = []
    for r in summaries:
        null_txt = ", ".join(f"{k}={v:,}" for k, v in r["nulls"].items() if v) or "0"
        rows.append(
            [
                r["series"].label,
                r["rows"],
                r["first"],
                r["last"],
                r["expected"],
                r["missing"],
                len(r["gaps"]),
                r["dupes"],
                null_txt,
            ]
        )
    out.append(
        _table(
            [
                "series",
                "rows",
                "first",
                "last",
                "expected slots",
                "missing slots",
                "gap ranges",
                "duplicate keys",
                "nulls",
            ],
            rows,
        )
    )

    out += ["", "## Gaps (largest 10 per series)", ""]
    any_gaps = False
    for r in summaries:
        if not r["gaps"]:
            continue
        any_gaps = True
        step = r["series"].step
        biggest = sorted(r["gaps"], key=lambda g: g[1] - g[0], reverse=True)[:10]
        out += [
            f"**{r['series'].label}**: {len(r['gaps'])} gap range(s)",
            "",
            _table(
                ["first missing", "last missing", "slots"],
                [[a, b, (b - a) // step + 1] for a, b in biggest],
            ),
            "",
        ]
    if not any_gaps:
        out.append("No gaps in any series.")

    days = dst_check(con, start)
    mismatched = [d for d in days if d[1] != d[2]]
    transitions = [d for d in days if d[2] != 48]
    out += [
        "",
        "## UK daylight-saving transitions (intensity)",
        "",
        "Settlement periods per UK local day. Clock-change days must have 46 (spring) "
        "or 50 (autumn) periods.",
        "",
        f"- Complete UK local days checked: {len(days):,}",
        f"- Days whose period count differs from the calendar: {len(mismatched):,}",
        "",
        _table(
            ["UK date", "periods stored", "periods expected", "ok"],
            [[d, n, e, "yes" if n == e else "NO"] for d, n, e in transitions],
        ),
    ]
    if mismatched:
        out += [
            "",
            "Mismatched days (first 20):",
            "",
            _table(
                ["UK date", "periods stored", "periods expected"],
                [list(m) for m in mismatched[:20]],
            ),
        ]

    out += ["", "## Value sanity", ""]
    ia = con.execute(
        """
        SELECT min(actual_gco2), max(actual_gco2), avg(actual_gco2),
               min(forecast_gco2), max(forecast_gco2), avg(forecast_gco2),
               count(*) FILTER (WHERE actual_gco2 < 0 OR forecast_gco2 < 0)
        FROM raw_intensity WHERE period_start_utc >= $start""",
        {"start": start},
    ).fetchone()
    out += [
        "Intensity (gCO2/kWh):",
        "",
        _table(
            ["", "min", "max", "mean"],
            [["actual", ia[0], ia[1], ia[2]], ["forecast", ia[3], ia[4], ia[5]]],
        ),
        "",
        f"Negative values: {ia[6]:,}",
        "",
    ]

    # A national average cannot exceed the dirtiest fuel's emission factor
    # (coal, roughly 900-1,000 gCO2/kWh), and GB has never had a zero-carbon
    # half-hour, so both are data errors. Staging nulls them out.
    suspect = con.execute(
        """
        SELECT period_start_utc, forecast_gco2, actual_gco2,
               concat_ws(', ',
                   CASE WHEN forecast_gco2 > 1000 THEN 'forecast > 1000' END,
                   CASE WHEN actual_gco2 > 1000 THEN 'actual > 1000' END,
                   CASE WHEN forecast_gco2 = 0 THEN 'forecast = 0' END,
                   CASE WHEN actual_gco2 = 0 THEN 'actual = 0' END) AS reason
        FROM raw_intensity
        WHERE period_start_utc >= $start
          AND (forecast_gco2 > 1000 OR actual_gco2 > 1000
               OR forecast_gco2 = 0 OR actual_gco2 = 0)
        ORDER BY period_start_utc""",
        {"start": start},
    ).fetchall()
    out += [f"Suspect intensity values (> 1,000 or exactly 0): {len(suspect):,}", ""]
    if suspect:
        out += [
            _table(["period start", "forecast", "actual", "reason"], [list(r) for r in suspect]),
            "",
        ]

    fuels = con.execute(
        """
        SELECT fuel, count(*) FROM raw_generation WHERE period_start_utc >= $start
        GROUP BY fuel ORDER BY fuel""",
        {"start": start},
    ).fetchall()
    g = con.execute(
        """
        WITH p AS (
            SELECT period_start_utc, count(*) AS n_fuels, round(sum(perc), 1) AS total
            FROM raw_generation WHERE period_start_utc >= $start GROUP BY period_start_utc
        )
        SELECT min(n_fuels), max(n_fuels), min(total), max(total),
               count(*) FILTER (WHERE total NOT BETWEEN 95 AND 105)
        FROM p""",
        {"start": start},
    ).fetchone()
    out += [
        "Generation mix:",
        "",
        f"- Fuels: {', '.join(f'{f} ({n:,})' for f, n in fuels)}",
        f"- Fuels per period: min {g[0]}, max {g[1]}",
        f"- Sum of percentages per period: min {g[2]}, max {g[3]}; "
        f"periods outside 95-105%: {g[4]:,}",
        "",
    ]

    same = [f"avg(CASE WHEN a.{v} = f.{v} THEN 100.0 ELSE 0.0 END)" for v in VARIABLES]
    w = con.execute(f"""
        SELECT CAST(year(a.time_utc) AS VARCHAR) AS yr, count(*) AS n, {", ".join(same)},
               avg(abs(a.wind_speed_100m - f.wind_speed_100m)) AS wind_mae
        FROM raw_weather_archive a
        JOIN raw_weather_hist_forecast f USING (location_id, time_utc)
        GROUP BY yr ORDER BY yr""").fetchall()
    out += [
        "## Weather: historical-forecast vs archive",
        "",
        "The Historical Forecast API stitches together the first hours of each model run, "
        "so at best it is a ~0-6h forecast. Where it is *identical* to the archive "
        "(observed conditions), it is returning outturn weather outright. Either way it "
        "would leak into a 24-48h model; leakage-free weather comes from the Previous Runs "
        "API instead. % of hours identical, all locations:",
        "",
        _table(
            [
                "year",
                "overlapping hours",
                *(f"{v} % identical" for v in VARIABLES),
                "wind 100m MAE (m/s)",
            ],
            [list(r) for r in w],
        ),
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    settings = load_settings()
    p = argparse.ArgumentParser(prog="python -m carbon_forecast.quality")
    p.add_argument("--db", default=settings["db_path"])
    p.add_argument("--out", default=str(REPORTS_DIR / "data_quality.md"))
    args = p.parse_args(argv)
    with connect(resolve(args.db)) as con:
        report = build_report(con, settings)
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(report)
    print(f"written to {out}")


if __name__ == "__main__":
    main()
