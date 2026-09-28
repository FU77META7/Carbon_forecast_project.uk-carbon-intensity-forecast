"""Carbon Intensity API (https://carbon-intensity.github.io/api-definitions/), national.

Verified behaviour (2026-09-28):
  * GET /intensity/{from}/{to} and /generation/{from}/{to} return every
    half-hour whose END time falls in [from, to], inclusive. Asking for slots
    starting s..e therefore means from=s+30min, to=e+30min.
  * /intensity rejects ranges longer than 31 days (docs say 14).
  * /generation returns HTTP 200 but silently drops everything after 31 Dec
    when from/to straddle a year boundary, so requests are split at year end.
  * Some periods are genuinely absent upstream (e.g. 2023-10-20 22:00 to
    2023-10-22 19:00); those stay as gaps in the data quality report.
  * Earliest data: intensity 2017-09-12, generation mix 2018-05-11.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

import duckdb

from carbon_forecast.ingest.http import HttpClient, HttpError
from carbon_forecast.ingest.ranges import missing_ranges, plan_chunks

log = logging.getLogger(__name__)

STEP = timedelta(minutes=30)
API_TS = "%Y-%m-%dT%H:%MZ"

_INTENSITY_SCHEMA = json.dumps(
    {
        "data": [
            {
                "from": "VARCHAR",
                "to": "VARCHAR",
                "intensity": {"forecast": "INTEGER", "actual": "INTEGER", "index": "VARCHAR"},
            }
        ]
    }
)

_GENERATION_SCHEMA = json.dumps(
    {
        "data": [
            {
                "from": "VARCHAR",
                "to": "VARCHAR",
                "generationmix": [{"fuel": "VARCHAR", "perc": "DOUBLE"}],
            }
        ]
    }
)

# A later fetch never replaces a known value with null (e.g. a re-request that
# races settlement), but does take revised non-null values.
INTENSITY_UPSERT = f"""
INSERT INTO raw_intensity
WITH rows AS (
    SELECT unnest(from_json($payload, '{_INTENSITY_SCHEMA}').data) AS r
)
SELECT
    strptime(r."from", '{API_TS}'),
    strptime(r."to", '{API_TS}'),
    r.intensity.forecast,
    r.intensity.actual,
    r.intensity."index",
    $ingested_at
FROM rows
ON CONFLICT (period_start_utc) DO UPDATE SET
    period_end_utc  = excluded.period_end_utc,
    forecast_gco2   = COALESCE(excluded.forecast_gco2, raw_intensity.forecast_gco2),
    actual_gco2     = COALESCE(excluded.actual_gco2, raw_intensity.actual_gco2),
    intensity_index = COALESCE(excluded.intensity_index, raw_intensity.intensity_index),
    ingested_at_utc = excluded.ingested_at_utc
"""

GENERATION_UPSERT = f"""
INSERT INTO raw_generation
WITH periods AS (
    SELECT unnest(from_json($payload, '{_GENERATION_SCHEMA}').data) AS p
),
mix AS (
    SELECT p."from" AS f, p."to" AS t, unnest(p.generationmix) AS g FROM periods
)
SELECT strptime(f, '{API_TS}'), strptime(t, '{API_TS}'), g.fuel, g.perc, $ingested_at
FROM mix
ON CONFLICT (period_start_utc, fuel) DO UPDATE SET
    period_end_utc  = excluded.period_end_utc,
    perc            = COALESCE(excluded.perc, raw_generation.perc),
    ingested_at_utc = excluded.ingested_at_utc
"""

# A slot counts as present once it has an actual, or once it was fetched more
# than two days after it ended (the null is then an upstream gap, not an
# unsettled period, and re-requesting it on every run would be pointless).
INTENSITY_PRESENT = """
    SELECT period_start_utc AS ts FROM raw_intensity
    WHERE actual_gco2 IS NOT NULL OR ingested_at_utc >= period_end_utc + INTERVAL 2 DAY
"""
GENERATION_PRESENT = "SELECT DISTINCT period_start_utc AS ts FROM raw_generation"


def split_at_year_end(chunks: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Split chunks so that every request's slot END times fall in one calendar year.
    /generation silently truncates a range whose from/to straddle 1 January
    (verified 2026-09-28); /intensity does not, but splitting is harmless there."""
    out = []
    for s, e in chunks:
        while (s + STEP).year != (e + STEP).year:
            # Slot 23:00-23:30 on 31 Dec; the 23:30 slot ends on 1 Jan, so it
            # belongs with the next year's request.
            last_in_year = datetime((s + STEP).year + 1, 1, 1) - 2 * STEP
            out.append((s, last_in_year))
            s = last_in_year + STEP
        out.append((s, e))
    return out


def _check(payload: dict) -> dict:
    if not isinstance(payload, dict) or "data" not in payload:
        raise HttpError(f"unexpected Carbon Intensity response: {str(payload)[:300]}")
    return payload


def load_intensity(con: duckdb.DuckDBPyConnection, payload: dict, ingested_at: datetime) -> int:
    args = {"payload": json.dumps(_check(payload)), "ingested_at": ingested_at}
    return con.execute(INTENSITY_UPSERT, args).fetchone()[0]


def load_generation(con: duckdb.DuckDBPyConnection, payload: dict, ingested_at: datetime) -> int:
    args = {"payload": json.dumps(_check(payload)), "ingested_at": ingested_at}
    return con.execute(GENERATION_UPSERT, args).fetchone()[0]


_ENDPOINTS = {
    # name: (path, present query, loader)
    "intensity": ("intensity", INTENSITY_PRESENT, load_intensity),
    "generation": ("generation", GENERATION_PRESENT, load_generation),
}


def ingest(
    con: duckdb.DuckDBPyConnection,
    client: HttpClient,
    endpoint: str,
    base_url: str,
    start: datetime,
    end: datetime,
    max_days: int,
    dry_run: bool = False,
) -> list[tuple[datetime, datetime]]:
    """Fetch and upsert every missing half-hour slot starting in [start, end].
    Returns the planned chunks (inclusive first/last slot starts)."""
    path, present_sql, loader = _ENDPOINTS[endpoint]
    gaps = missing_ranges(con, present_sql, start, end, STEP)
    chunks = split_at_year_end(plan_chunks(gaps, STEP, timedelta(days=max_days)))
    log.info("%s: %d missing range(s) -> %d request(s)", endpoint, len(gaps), len(chunks))
    for i, (s, e) in enumerate(chunks, 1):
        if dry_run:
            log.info("  [dry-run] %s %s -> %s", endpoint, s, e)
            continue
        # Periods are matched on their end time, so from/to are the first and last slot ends.
        url = f"{base_url}/{path}/{(s + STEP).strftime(API_TS)}/{(e + STEP).strftime(API_TS)}"
        payload = client.get_json(url)
        n = loader(con, payload, datetime.now(UTC).replace(tzinfo=None))
        log.info("  [%d/%d] %s %s -> %s: %d rows", i, len(chunks), endpoint, s, e, n)
    return chunks
