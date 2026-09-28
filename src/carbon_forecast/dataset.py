"""Load training_set from DuckDB and split it by time."""

from datetime import datetime

import duckdb
import pandas as pd

KEYS = ["origin_time_utc", "horizon_h", "target_time_utc"]
TARGET = "y_actual_gco2"
# Prefixes that must never be model inputs: the target, the NESO reference
# forecast, and provenance timestamps.
NEVER_FEATURES = ("y_", "ref_", "asof_")
LEAKY_PREFIXES = ("oracle_",)


def load_training_set(
    con: duckdb.DuckDBPyConnection,
    start: datetime | None = None,
    end: datetime | None = None,
    labelled_only: bool = True,
) -> pd.DataFrame:
    """Rows with origin_time_utc in [start, end)."""
    where = ["TRUE"]
    params: dict = {}
    if start is not None:
        where.append("origin_time_utc >= $start")
        params["start"] = start
    if end is not None:
        where.append("origin_time_utc < $end")
        params["end"] = end
    if labelled_only:
        where.append(f"{TARGET} IS NOT NULL")
    sql = (
        "SELECT COLUMNS(c -> NOT starts_with(c, 'asof_')) FROM training_set "
        f"WHERE {' AND '.join(where)}"
    )
    return con.execute(sql, params).df()


def feature_columns(df: pd.DataFrame, prefixes: list[str], allow_leaky: bool = False) -> list[str]:
    for p in prefixes:
        if p.startswith(NEVER_FEATURES):
            raise ValueError(f"prefix {p!r} can never be a feature")
        if p.startswith(LEAKY_PREFIXES) and not allow_leaky:
            raise ValueError(f"prefix {p!r} is leaky; pass allow_leaky=True for oracle experiments")
    cols = [c for c in df.columns if c.startswith(tuple(prefixes))]
    if not cols:
        raise ValueError(f"no columns match {prefixes}")
    return cols


def time_split(
    df: pd.DataFrame, boundary: datetime, train_start: datetime | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train on rows whose TARGET is before `boundary` (purging origins whose
    targets straddle it); evaluate on rows whose ORIGIN is at or after it."""
    train = df[df["target_time_utc"] < boundary]
    if train_start is not None:
        train = train[train["origin_time_utc"] >= train_start]
    return train, df[df["origin_time_utc"] >= boundary]
