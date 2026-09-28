"""Incremental ingestion into DuckDB raw_* tables."""

import logging
from datetime import date, datetime, timedelta

import duckdb

from carbon_forecast.db import init_raw_schema
from carbon_forecast.ingest import carbon_intensity, open_meteo
from carbon_forecast.ingest.http import HttpClient

log = logging.getLogger(__name__)

SOURCES = (
    "intensity",
    "generation",
    "weather_archive",
    "weather_hist_forecast",
    "weather_prev_runs",
)


def run_ingestion(
    con: duckdb.DuckDBPyConnection,
    settings: dict,
    start: date,
    end: date,
    sources: tuple[str, ...] = SOURCES,
    dry_run: bool = False,
    ci_client: HttpClient | None = None,
    om_client: HttpClient | None = None,
) -> dict[str, int]:
    """Ingest UTC dates start..end (inclusive). Returns planned request counts per source."""
    unknown = set(sources) - set(SOURCES)
    if unknown:
        raise ValueError(f"unknown source(s): {sorted(unknown)}")
    init_raw_schema(con)

    ci, om = settings["carbon_intensity"], settings["open_meteo"]
    ci_client = ci_client or HttpClient(min_interval_s=ci["min_interval_s"])
    om_client = om_client or HttpClient(min_interval_s=om["min_interval_s"])
    open_meteo.upsert_locations(con, settings["locations"])

    first = datetime.combine(start, datetime.min.time())
    last_day = datetime.combine(end, datetime.min.time())
    planned: dict[str, int] = {}
    for source in sources:
        if source in ("intensity", "generation"):
            chunks = carbon_intensity.ingest(
                con,
                ci_client,
                source,
                ci["base_url"],
                first,
                last_day + timedelta(days=1) - carbon_intensity.STEP,
                ci["max_days_per_request"],
                dry_run,
            )
        else:
            src_first = first
            if source == "weather_prev_runs":
                src_first = max(
                    first, datetime.combine(om["prev_runs_start_date"], datetime.min.time())
                )
            chunks = open_meteo.ingest(
                con,
                om_client,
                source,
                om,
                settings["locations"],
                src_first,
                last_day + timedelta(days=1) - open_meteo.STEP,
                dry_run,
            )
        planned[source] = len(chunks)
    return planned
