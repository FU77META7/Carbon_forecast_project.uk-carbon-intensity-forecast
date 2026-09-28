"""Build the SQL feature layers (sql/01-05) on top of the raw tables.

python -m carbon_forecast.features  -> builds `training_set` in the project DuckDB
"""

import argparse
from datetime import datetime, timedelta

import duckdb
import holidays

from carbon_forecast.config import load_settings, resolve
from carbon_forecast.db import connect, init_raw_schema, run_sql_files

# England & Wales holidays drive most GB demand; Scotland's differ (2 Jan,
# St Andrew's Day, August bank holiday) and get their own flag.
HOLIDAY_REGIONS = ("ENG", "SCT")
LAYER_TABLES = ("calendar", "feat_history", "feat_weather", "training_set")


def load_bank_holidays(con: duckdb.DuckDBPyConnection, years: range) -> int:
    con.execute("""
        CREATE OR REPLACE TABLE ref_bank_holidays (
            holiday_date DATE    NOT NULL,
            region       VARCHAR NOT NULL,
            name         VARCHAR NOT NULL,
            PRIMARY KEY (holiday_date, region)
        )""")
    rows = [
        (day, region, name)
        for region in HOLIDAY_REGIONS
        for day, name in holidays.country_holidays("GB", subdiv=region, years=years).items()
    ]
    con.executemany("INSERT INTO ref_bank_holidays VALUES (?, ?, ?)", rows)
    return len(rows)


def spine_bounds(con: duckdb.DuckDBPyConnection, settings: dict) -> tuple[datetime, datetime]:
    """Calendar spine: configured start to 3 days past the newest intensity data,
    so the latest origins still have a full 48h of target periods."""
    latest = con.execute("SELECT max(period_start_utc) FROM raw_intensity").fetchone()[0]
    if latest is None:
        raise RuntimeError("raw_intensity is empty; run `python -m carbon_forecast.ingest` first")
    start = datetime.combine(settings["start_date"], datetime.min.time())
    end = datetime.combine(latest.date(), datetime.min.time()) + timedelta(days=3, minutes=-30)
    return start, end


def set_variables(con: duckdb.DuckDBPyConnection, settings: dict, start: datetime, end: datetime):
    f = settings["features"]
    values = {
        "spine_start": start,
        "spine_end": end,
        "origin_hours_utc": list(f["origin_hours_utc"]),
        "horizon_min_h": f["horizon_min_h"],
        "horizon_max_h": f["horizon_max_h"],
        "data_availability_lag_minutes": f["data_availability_lag_minutes"],
        "weather_forecast_availability_hours": f["weather_forecast_availability_hours"],
        "suspect_max_gco2": f["suspect_max_gco2"],
        "wind_cut_in_ms": float(f["wind_cut_in_ms"]),
        "wind_rated_ms": float(f["wind_rated_ms"]),
        "wind_cut_out_ms": float(f["wind_cut_out_ms"]),
    }
    for name, value in values.items():
        con.execute(f"SET VARIABLE {name} = ?", [value])


def build_features(con: duckdb.DuckDBPyConnection, settings: dict) -> dict[str, int]:
    """Run sql/00-05 in order; returns row counts of the materialised layers."""
    init_raw_schema(con)
    start, end = spine_bounds(con, settings)
    load_bank_holidays(con, range(start.year, end.year + 1))
    set_variables(con, settings, start, end)
    run_sql_files(con)
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in LAYER_TABLES}


def main(argv: list[str] | None = None) -> None:
    settings = load_settings()
    p = argparse.ArgumentParser(prog="python -m carbon_forecast.features")
    p.add_argument("--db", default=settings["db_path"])
    args = p.parse_args(argv)
    with connect(resolve(args.db)) as con:
        counts = build_features(con, settings)
    for table, n in counts.items():
        print(f"{table:>14}: {n:,} rows")


if __name__ == "__main__":
    main()
