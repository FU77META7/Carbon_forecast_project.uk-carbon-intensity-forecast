"""Open-Meteo hourly weather (https://open-meteo.com/, no API key).

Three products, verified 2026-09-28:
  * archive          - reanalysis/observed conditions. Leaky as a forecast input.
  * hist_forecast    - first hours of successive model runs stitched together,
                       i.e. a ~0-6h lead, so NOT a stand-in for a 24-48h-ahead
                       forecast. At our GB sites it returns archive values for all
                       variables in 2019 and archive wind through at least mid-2024
                       (see the data quality report's year-by-year comparison).
  * prev_runs        - `<var>_previous_dayN`: value predicted N*24h before the
                       valid time. Leakage-free; complete from 2024-03-09.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb

from carbon_forecast.ingest.http import HttpClient, HttpError
from carbon_forecast.ingest.ranges import missing_ranges, plan_chunks

log = logging.getLogger(__name__)

STEP = timedelta(hours=1)
VARIABLES = ("wind_speed_100m", "shortwave_radiation", "temperature_2m", "cloud_cover")
API_TS = "%Y-%m-%dT%H:%M"
COMMON_PARAMS = {"timezone": "GMT", "wind_speed_unit": "ms"}

SINGLE_RUN_TABLES = {
    "weather_archive": "raw_weather_archive",
    "weather_hist_forecast": "raw_weather_hist_forecast",
}


def _hourly_upsert_sql(table: str, api_cols: list[str], lead_days: int | None) -> str:
    """Upsert for one product. `api_cols` are the response keys matching VARIABLES,
    in order (they differ only for the previous-runs `_previous_dayN` suffix)."""
    schema = json.dumps({"hourly": {"time": ["VARCHAR"], **{c: ["DOUBLE"] for c in api_cols}}})
    unnests = ",\n        ".join(
        f'unnest(h."{c}") AS "{v}"' for c, v in zip(api_cols, VARIABLES, strict=True)
    )
    lead_col = f"{lead_days} AS lead_days, " if lead_days is not None else ""
    key = "location_id, time_utc" + (", lead_days" if lead_days is not None else "")
    updates = ",\n    ".join(f"{v} = COALESCE(excluded.{v}, {table}.{v})" for v in VARIABLES)
    return f"""
INSERT INTO {table} (location_id, time_utc, {"lead_days, " if lead_days is not None else ""}
                     {", ".join(VARIABLES)}, ingested_at_utc)
WITH h AS (
    SELECT from_json($payload, '{schema}').hourly AS h
),
rows AS (
    SELECT unnest(h.time) AS t,
        {unnests}
    FROM h
)
SELECT $location_id, strptime(t, '{API_TS}'), {lead_col}{", ".join(VARIABLES)}, $ingested_at
FROM rows
WHERE COALESCE({", ".join(VARIABLES)}) IS NOT NULL  -- skip hours not yet published
ON CONFLICT ({key}) DO UPDATE SET
    {updates},
    ingested_at_utc = excluded.ingested_at_utc
"""


def load_single_run(
    con: duckdb.DuckDBPyConnection,
    table: str,
    location_id: str,
    payload: dict,
    ingested_at: datetime,
) -> int:
    sql = _hourly_upsert_sql(table, list(VARIABLES), lead_days=None)
    args = {
        "payload": json.dumps(_check(payload)),
        "location_id": location_id,
        "ingested_at": ingested_at,
    }
    return con.execute(sql, args).fetchone()[0]


def load_prev_runs(
    con: duckdb.DuckDBPyConnection,
    location_id: str,
    payload: dict,
    lead_days: list[int],
    ingested_at: datetime,
) -> int:
    args = {
        "payload": json.dumps(_check(payload)),
        "location_id": location_id,
        "ingested_at": ingested_at,
    }
    n = 0
    for lead in lead_days:
        cols = [f"{v}_previous_day{lead}" for v in VARIABLES]
        n += con.execute(_hourly_upsert_sql("raw_weather_prev_runs", cols, lead), args).fetchone()[
            0
        ]
    return n


def _check(payload: Any) -> dict:
    if not isinstance(payload, dict) or "hourly" not in payload:
        raise HttpError(f"unexpected Open-Meteo response: {str(payload)[:300]}")
    return payload


def upsert_locations(con: duckdb.DuckDBPyConnection, locations: list[dict]) -> None:
    con.executemany(
        """INSERT INTO raw_weather_locations VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (location_id) DO UPDATE SET name = excluded.name, role = excluded.role,
               latitude = excluded.latitude, longitude = excluded.longitude""",
        [
            (loc["id"], loc["name"], loc["role"], loc["latitude"], loc["longitude"])
            for loc in locations
        ],
    )


def ingest(
    con: duckdb.DuckDBPyConnection,
    client: HttpClient,
    product: str,
    settings: dict,
    locations: list[dict],
    start: datetime,
    end: datetime,
    dry_run: bool = False,
) -> list[tuple[str, datetime, datetime]]:
    """Fetch and upsert missing hours in [start, end] for every location.
    Returns the planned (location_id, first hour, last hour) requests."""
    if product == "weather_prev_runs":
        leads = list(settings["prev_runs_lead_days"])
        url = settings["prev_runs_url"]
        hourly = ",".join(f"{v}_previous_day{n}" for v in VARIABLES for n in leads)
        extra = {"models": settings["prev_runs_model"]}
        # Complete only when every lead day is present for that hour.
        present_sql = (
            "SELECT time_utc AS ts FROM raw_weather_prev_runs WHERE location_id = $location_id "
            f"GROUP BY time_utc HAVING count(*) = {len(leads)}"
        )
    else:
        table = SINGLE_RUN_TABLES[product]
        url = settings["archive_url" if product == "weather_archive" else "hist_forecast_url"]
        hourly = ",".join(VARIABLES)
        extra = {}
        present_sql = f"SELECT time_utc AS ts FROM {table} WHERE location_id = $location_id"

    planned = []
    max_span = timedelta(days=settings["max_days_per_request"])
    for loc in locations:
        gaps = missing_ranges(con, present_sql, start, end, STEP, {"location_id": loc["id"]})
        chunks = plan_chunks(gaps, STEP, max_span)
        log.info(
            "%s/%s: %d missing range(s) -> %d request(s)",
            product,
            loc["id"],
            len(gaps),
            len(chunks),
        )
        for s, e in chunks:
            planned.append((loc["id"], s, e))
            if dry_run:
                log.info("  [dry-run] %s/%s %s -> %s", product, loc["id"], s.date(), e.date())
                continue
            params = {
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "start_date": s.date().isoformat(),
                "end_date": e.date().isoformat(),
                "hourly": hourly,
                **COMMON_PARAMS,
                **extra,
            }
            payload = client.get_json(url, params)
            now = datetime.now(UTC).replace(tzinfo=None)
            if product == "weather_prev_runs":
                n = load_prev_runs(con, loc["id"], payload, leads, now)
            else:
                n = load_single_run(con, table, loc["id"], payload, now)
            log.info("  %s/%s %s -> %s: %d rows", product, loc["id"], s.date(), e.date(), n)
    return planned
