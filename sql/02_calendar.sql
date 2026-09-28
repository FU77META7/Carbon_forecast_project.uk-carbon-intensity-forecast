-- Layer 2: calendar. One row per UTC half-hour on a gap-free spine, with the
-- UK-local calendar attributes a target period is known to have in advance.
-- The spine is also what later layers LEFT JOIN data onto, so gaps in the
-- source data become explicit NULL rows instead of silently shortening windows.
-- ref_bank_holidays is loaded from the `holidays` package by carbon_forecast.features.

CREATE OR REPLACE TABLE calendar AS
WITH spine AS (
    SELECT unnest(generate_series(
        getvariable('spine_start'), getvariable('spine_end'), INTERVAL 30 MINUTE
    )) AS period_start_utc
),
localised AS (
    SELECT
        period_start_utc,
        timezone('Europe/London', period_start_utc AT TIME ZONE 'UTC') AS local_ts
    FROM spine
),
with_day AS (
    SELECT
        *,
        CAST(local_ts AS DATE) AS uk_date,
        -- UTC instant of local midnight; differs from 00:00 UTC during BST.
        timezone('Europe/London', CAST(local_ts AS DATE)::TIMESTAMP) AS uk_day_start
    FROM localised
)
SELECT
    d.period_start_utc,
    d.local_ts,
    d.uk_date,
    -- Settlement periods count half-hours from local midnight in elapsed time,
    -- so clock-change days run 1..46 (spring) and 1..50 (autumn).
    CAST((epoch(d.period_start_utc) - epoch(d.uk_day_start)) / 1800 AS INTEGER) + 1
        AS settlement_period,
    CAST((epoch(timezone('Europe/London', (d.uk_date + 1)::TIMESTAMP))
          - epoch(d.uk_day_start)) / 1800 AS INTEGER) AS periods_in_uk_day,
    hour(d.local_ts) + minute(d.local_ts) / 60.0 AS local_hour,
    isodow(d.uk_date) AS day_of_week,  -- 1 = Monday
    isodow(d.uk_date) >= 6 AS is_weekend,
    month(d.uk_date) AS month,
    dayofyear(d.uk_date) AS day_of_year,
    d.local_ts - d.period_start_utc = INTERVAL 1 HOUR AS is_dst,
    EXISTS (SELECT 1 FROM ref_bank_holidays h
            WHERE h.holiday_date = d.uk_date AND h.region = 'ENG') AS is_bank_holiday_ew,
    EXISTS (SELECT 1 FROM ref_bank_holidays h
            WHERE h.holiday_date = d.uk_date AND h.region = 'SCT') AS is_bank_holiday_scot
FROM with_day d
ORDER BY d.period_start_utc;
