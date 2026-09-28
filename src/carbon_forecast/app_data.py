"""Read-only queries behind the Streamlit app. Nothing here trains or refits;
it only reads tables written by `backtest` and `evaluate`."""

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from carbon_forecast.evaluate import MODELS

REQUIRED_TABLES = (
    "backtest_results",
    "backtest_metrics_by_horizon",
    "backtest_metrics_overall",
    "backtest_interval_coverage",
)
ISSUE_HOURS = (0, 6, 12, 18)


def connect_readonly(path: str | Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path), read_only=True)
    con.execute("SET TimeZone = 'UTC'")
    return con


def missing_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    have = {
        r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    return [t for t in REQUIRED_TABLES if t not in have]


def target_date_range(con: duckdb.DuckDBPyConnection) -> tuple[date, date]:
    """First and last UTC target dates with an actual in the backtest."""
    lo, hi = con.execute(
        "SELECT min(target_time_utc)::DATE, max(target_time_utc)::DATE FROM backtest_results "
        "WHERE y_actual_gco2 IS NOT NULL"
    ).fetchone()
    return lo, hi


def day_ahead(
    con: duckdb.DuckDBPyConnection, start: date, end: date, issue_hour: int, models: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Forecasts issued daily at `issue_hour` UTC for 24-47.5h ahead, which covers
    every target half-hour exactly once. Returns (long, wide): long has one row
    per (target, series) for plotting; wide has one row per target."""
    if issue_hour not in ISSUE_HOURS:
        raise ValueError(f"issue_hour must be one of {ISSUE_HOURS}")
    unknown = set(models) - set(MODELS)
    if unknown:
        raise ValueError(f"unknown models: {sorted(unknown)}")
    cols = ", ".join(["y_actual_gco2", *models])  # names validated above
    wide = con.execute(
        f"""
        SELECT target_time_utc, origin_time_utc, horizon_h, {cols},
               weather_forecast_cp10, weather_forecast_cp90
        FROM backtest_results
        WHERE hour(origin_time_utc) = $h AND minute(origin_time_utc) = 0
          AND horizon_h < 48
          AND target_time_utc >= $start AND target_time_utc < $end
        ORDER BY target_time_utc
        """,
        {"h": issue_hour, "start": start, "end": end + timedelta(days=1)},
    ).df()
    con.register(
        "wide_df",
        wide[["target_time_utc", "origin_time_utc", "horizon_h", "y_actual_gco2", *models]],
    )
    long = con.execute("""
        UNPIVOT wide_df
        ON COLUMNS(* EXCLUDE (target_time_utc, origin_time_utc, horizon_h))
        INTO NAME series VALUE gco2
    """).df()
    con.unregister("wide_df")
    return long, wide


def window_scores(wide: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """MAE and bias over the displayed window, on rows where every shown model exists."""
    rows = wide.dropna(subset=["y_actual_gco2", *models])
    out = []
    for m in models:
        err = rows[m] - rows["y_actual_gco2"]
        out.append(
            {
                "model": MODELS[m][0],
                "MAE (gCO2/kWh)": err.abs().mean(),
                "bias (gCO2/kWh)": err.mean(),
                "rows": len(rows),
            }
        )
    return pd.DataFrame(out)


def window_coverage(wide: pd.DataFrame) -> float | None:
    rows = wide.dropna(subset=["y_actual_gco2", "weather_forecast_cp10", "weather_forecast_cp90"])
    if rows.empty:
        return None
    y = rows["y_actual_gco2"]
    return float(
        ((y >= rows["weather_forecast_cp10"]) & (y <= rows["weather_forecast_cp90"])).mean()
    )


def metrics_by_horizon(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("SELECT * FROM backtest_metrics_by_horizon ORDER BY model, horizon_h").df()


def overall(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("SELECT * FROM backtest_metrics_overall").df().set_index("model")


def interval_coverage(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """10-90% coverage table (raw and conformal) written by `evaluate`."""
    return con.execute("SELECT * FROM backtest_interval_coverage").df()
