-- Layer 3: history features, one row per half-hour H on the gap-free spine.
-- Every value on row H uses only data from periods starting at or before H.
-- Layer 5 reads the row for H = the newest period usable at the forecast
-- origin, which is what makes these features origin-anchored and leak-free.
--
-- Because the spine has no gaps, LAG(x, 48) is exactly 24 hours back, and a
-- missing source period shows up as NULL rather than shifting the lag. Window
-- frames use RANGE with explicit intervals so they are time-based by definition.

CREATE OR REPLACE TABLE feat_history AS
WITH series AS (
    SELECT
        c.period_start_utc,
        i.actual_gco2,
        g.gas_pct,
        g.wind_pct,
        g.solar_pct,
        g.nuclear_pct,
        g.imports_pct
    FROM calendar c
    LEFT JOIN stg_intensity i USING (period_start_utc)
    LEFT JOIN stg_generation g USING (period_start_utc)
    WHERE c.period_start_utc <= (SELECT max(period_start_utc) FROM stg_intensity)
)
SELECT
    period_start_utc,

    actual_gco2                                             AS intensity,
    lag(actual_gco2, 48)  OVER w_ordered                    AS intensity_minus_24h,
    lag(actual_gco2, 336) OVER w_ordered                    AS intensity_minus_168h,

    avg(actual_gco2)         OVER w_24h                     AS intensity_mean_24h,
    stddev_samp(actual_gco2) OVER w_24h                     AS intensity_std_24h,
    min(actual_gco2)         OVER w_24h                     AS intensity_min_24h,
    max(actual_gco2)         OVER w_24h                     AS intensity_max_24h,
    count(actual_gco2)       OVER w_24h                     AS intensity_obs_24h,  -- of 48
    avg(actual_gco2)         OVER w_7d                      AS intensity_mean_7d,
    stddev_samp(actual_gco2) OVER w_7d                      AS intensity_std_7d,
    count(actual_gco2)       OVER w_7d                      AS intensity_obs_7d,   -- of 336

    gas_pct,
    nuclear_pct,
    imports_pct,
    wind_pct,
    wind_pct - lag(wind_pct, 48) OVER w_ordered             AS wind_pct_change_24h,
    avg(wind_pct) OVER w_24h                                AS wind_pct_mean_24h,
    solar_pct,
    solar_pct - lag(solar_pct, 48) OVER w_ordered           AS solar_pct_change_24h,
    avg(solar_pct) OVER w_24h                               AS solar_pct_mean_24h,
    gas_pct - lag(gas_pct, 48) OVER w_ordered               AS gas_pct_change_24h
FROM series
WINDOW
    w_ordered AS (ORDER BY period_start_utc),
    w_24h AS (ORDER BY period_start_utc
              RANGE BETWEEN INTERVAL '23 hours 30 minutes' PRECEDING AND CURRENT ROW),
    w_7d  AS (ORDER BY period_start_utc
              RANGE BETWEEN INTERVAL '167 hours 30 minutes' PRECEDING AND CURRENT ROW)
ORDER BY period_start_utc;
