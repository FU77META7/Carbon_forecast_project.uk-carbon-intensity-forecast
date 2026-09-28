"""Work out which periods are missing from a table and plan API requests for them."""

from datetime import datetime, timedelta
from typing import Any

import duckdb

# Gaps-and-islands: expected grid timestamps minus those present, then group
# consecutive missing slots (slot index minus row number is constant within a run).
_MISSING_RANGES_SQL = """
WITH expected AS (
    SELECT unnest(generate_series($start::TIMESTAMP, $end::TIMESTAMP, to_seconds($step_s))) AS ts
),
present AS ({present_sql}),
missing AS (
    SELECT e.ts FROM expected e ANTI JOIN present p ON e.ts = p.ts
),
islands AS (
    SELECT ts, CAST(epoch(ts) AS BIGINT) // $step_s - row_number() OVER (ORDER BY ts) AS island
    FROM missing
)
SELECT min(ts) AS range_start, max(ts) AS range_end, count(*) AS n_slots
FROM islands
GROUP BY island
ORDER BY range_start
"""


def missing_ranges(
    con: duckdb.DuckDBPyConnection,
    present_sql: str,
    start: datetime,
    end: datetime,
    step: timedelta,
    params: dict[str, Any] | None = None,
) -> list[tuple[datetime, datetime]]:
    """Inclusive (first, last) slot of each run of grid slots in [start, end] that
    `present_sql` (a trusted query yielding a `ts` column) does not return."""
    sql = _MISSING_RANGES_SQL.format(present_sql=present_sql)
    args = {"start": start, "end": end, "step_s": int(step.total_seconds()), **(params or {})}
    return [(s, e) for s, e, _ in con.execute(sql, args).fetchall()]


def plan_chunks(
    ranges: list[tuple[datetime, datetime]], step: timedelta, max_span: timedelta
) -> list[tuple[datetime, datetime]]:
    """Merge nearby missing ranges and split long ones so that every chunk
    (inclusive first/last slot) spans at most `max_span` of time."""
    chunks: list[tuple[datetime, datetime]] = []
    for s, e in ranges:
        if chunks and e + step - chunks[-1][0] <= max_span:
            chunks[-1] = (chunks[-1][0], e)
            continue
        while e + step - s > max_span:
            cut = s + max_span - step
            chunks.append((s, cut))
            s = cut + step
        chunks.append((s, e))
    return chunks
