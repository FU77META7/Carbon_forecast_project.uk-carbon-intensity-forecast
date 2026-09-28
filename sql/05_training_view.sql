-- Layer 5: model-ready table, one row per (origin_time_utc, horizon_h).
-- target_time_utc = origin + horizon; horizons run every 30 min from
-- horizon_min_h to horizon_max_h (direct multi-horizon forecasting).
--
-- Column groups (the model code selects by prefix):
--   y_*       target: cleaned actual intensity at target_time_utc (NULL if missing)
--   f_*       leak-free features: history known at the origin, target-time calendar
--   wxf_*     leak-free weather FORECAST for the target time (from 2024-03-09 only)
--   oracle_*  OBSERVED weather at the target time. LEAKY - an upper-bound
--             experiment only, never usable in a deployed forecast.
--   ref_*     NESO's published forecast for the target; a comparison baseline,
--             never a feature (its issue time is undocumented).
--   asof_*    when each group of information became available; tests assert
--             every asof_* <= origin_time_utc.
--
-- Availability rules (settings.yaml -> features):
--   * a half-hour's intensity/mix is usable data_availability_lag_minutes after it
--     ends, so the newest usable period at origin O starts at
--     O - 30 min - lag ("cutoff").
--   * a weather forecast predicted N days before valid time T is usable from
--     T - N*24h + weather_forecast_availability_hours, where T is the LATEST
--     hourly input to the period (h0 + 1h, see layer 4), not the period itself.

CREATE OR REPLACE TABLE training_set AS
WITH horizons AS (
    SELECT unnest(generate_series(
        CAST(getvariable('horizon_min_h') * 2 AS BIGINT),
        CAST(getvariable('horizon_max_h') * 2 AS BIGINT)
    )) / 2.0 AS horizon_h
),
origins AS (
    SELECT
        period_start_utc AS origin_time_utc,
        period_start_utc - to_minutes(30 + getvariable('data_availability_lag_minutes'))
            AS cutoff_utc
    FROM calendar
    WHERE minute(period_start_utc) = 0
      AND list_contains(getvariable('origin_hours_utc'), hour(period_start_utc))
      -- need 7 days of history plus the availability lag for the weekly features
      AND period_start_utc >= getvariable('spine_start') + INTERVAL 8 DAY
      AND period_start_utc + to_minutes(CAST(getvariable('horizon_max_h') * 60 AS BIGINT))
          <= getvariable('spine_end')
),
grid AS (
    SELECT
        o.origin_time_utc,
        o.cutoff_utc,
        h.horizon_h,
        o.origin_time_utc + to_minutes(CAST(h.horizon_h * 60 AS BIGINT)) AS target_time_utc,
        -- Seasonal lags: the most recent same-time-of-day (or -week) value that
        -- is already published at the origin. For 24-48h horizons the "daily"
        -- lag is 2 days back (3 days for h > 46.5h), never 1.
        CAST(ceil((h.horizon_h * 60 + 30 + getvariable('data_availability_lag_minutes'))
                  / 1440.0) AS INTEGER) AS seasonal_lag_days
    FROM origins o
    CROSS JOIN horizons h
),
grid_wx AS (
    -- A period's weather is built from the hourly values at h0 and h1 = h0 + 1h
    -- (layer 4), so the forecast must be available for h1, the later of the two.
    -- Choose the shortest lead day whose h1 forecast is usable at the origin.
    SELECT
        *,
        CAST(ceil(((epoch(wx_last_input_utc) - epoch(origin_time_utc)) / 3600.0
                   + getvariable('weather_forecast_availability_hours')) / 24.0) AS INTEGER)
            AS wx_lead_days
    FROM (
        SELECT *, date_trunc('hour', target_time_utc) + INTERVAL 1 HOUR AS wx_last_input_utc
        FROM grid
    )
)
SELECT
    g.origin_time_utc,
    g.horizon_h,
    g.target_time_utc,

    y.actual_gco2                         AS y_actual_gco2,
    y.forecast_gco2                       AS ref_neso_forecast_gco2,

    -- history anchored at the origin (newest usable period = cutoff)
    fh.intensity                          AS f_intensity_latest,
    fh.intensity_minus_24h                AS f_intensity_latest_minus_24h,
    fh.intensity_minus_168h               AS f_intensity_latest_minus_168h,
    fh.intensity_mean_24h                 AS f_intensity_mean_24h,
    fh.intensity_std_24h                  AS f_intensity_std_24h,
    fh.intensity_min_24h                  AS f_intensity_min_24h,
    fh.intensity_max_24h                  AS f_intensity_max_24h,
    fh.intensity_mean_7d                  AS f_intensity_mean_7d,
    fh.intensity_std_7d                   AS f_intensity_std_7d,
    fh.intensity_obs_24h                  AS f_intensity_obs_24h,
    fh.gas_pct                            AS f_gas_pct_latest,
    fh.gas_pct_change_24h                 AS f_gas_pct_change_24h,
    fh.nuclear_pct                        AS f_nuclear_pct_latest,
    fh.imports_pct                        AS f_imports_pct_latest,
    fh.wind_pct                           AS f_wind_pct_latest,
    fh.wind_pct_change_24h                AS f_wind_pct_change_24h,
    fh.wind_pct_mean_24h                  AS f_wind_pct_mean_24h,
    fh.solar_pct                          AS f_solar_pct_latest,
    fh.solar_pct_change_24h               AS f_solar_pct_change_24h,
    fh.solar_pct_mean_24h                 AS f_solar_pct_mean_24h,

    -- same time of day / week as the target, but already published at the origin
    sd.actual_gco2                        AS f_intensity_target_seasonal_day,
    g.seasonal_lag_days                   AS f_seasonal_lag_days,
    sw.actual_gco2                        AS f_intensity_target_minus_168h,

    -- forecast set-up and target-time calendar (known in advance)
    g.horizon_h                           AS f_horizon_h,
    hour(g.origin_time_utc)               AS f_origin_hour_utc,
    c.settlement_period                   AS f_target_settlement_period,
    c.local_hour                          AS f_target_local_hour,
    c.day_of_week                         AS f_target_day_of_week,
    c.is_weekend::INTEGER                 AS f_target_is_weekend,
    c.month                               AS f_target_month,
    c.day_of_year                         AS f_target_day_of_year,
    c.is_dst::INTEGER                     AS f_target_is_dst,
    c.is_bank_holiday_ew::INTEGER         AS f_target_is_bank_holiday_ew,
    c.is_bank_holiday_scot::INTEGER       AS f_target_is_bank_holiday_scot,

    -- weather forecast for the target (leak-free)
    wf.wind_speed_100m_mean               AS wxf_wind_speed_100m_mean,
    wf.wind_speed_100m_min                AS wxf_wind_speed_100m_min,
    wf.wind_speed_100m_max                AS wxf_wind_speed_100m_max,
    wf.wind_power_frac_mean               AS wxf_wind_power_frac_mean,
    wf.solar_radiation_mean               AS wxf_solar_radiation_mean,
    wf.solar_cloud_cover_mean             AS wxf_solar_cloud_cover_mean,
    wf.demand_temperature                 AS wxf_demand_temperature,

    -- observed weather at the target (LEAKY oracle)
    wo.wind_speed_100m_mean               AS oracle_wind_speed_100m_mean,
    wo.wind_speed_100m_min                AS oracle_wind_speed_100m_min,
    wo.wind_speed_100m_max                AS oracle_wind_speed_100m_max,
    wo.wind_power_frac_mean               AS oracle_wind_power_frac_mean,
    wo.solar_radiation_mean               AS oracle_solar_radiation_mean,
    wo.solar_cloud_cover_mean             AS oracle_solar_cloud_cover_mean,
    wo.demand_temperature                 AS oracle_demand_temperature,

    -- provenance: when each input became available
    g.cutoff_utc + to_minutes(30 + getvariable('data_availability_lag_minutes'))
        AS asof_history_utc,
    g.target_time_utc - to_days(g.seasonal_lag_days)
        + to_minutes(30 + getvariable('data_availability_lag_minutes'))
        AS asof_seasonal_day_utc,
    g.target_time_utc - INTERVAL 168 HOUR
        + to_minutes(30 + getvariable('data_availability_lag_minutes'))
        AS asof_seasonal_week_utc,
    g.wx_last_input_utc - to_days(g.wx_lead_days)
        + to_hours(getvariable('weather_forecast_availability_hours'))
        AS asof_weather_forecast_utc
FROM grid_wx g
JOIN calendar c
  ON c.period_start_utc = g.target_time_utc
LEFT JOIN stg_intensity y
  ON y.period_start_utc = g.target_time_utc
LEFT JOIN feat_history fh
  ON fh.period_start_utc = g.cutoff_utc
LEFT JOIN stg_intensity sd
  ON sd.period_start_utc = g.target_time_utc - to_days(g.seasonal_lag_days)
LEFT JOIN stg_intensity sw
  ON sw.period_start_utc = g.target_time_utc - INTERVAL 168 HOUR
LEFT JOIN feat_weather wf
  ON wf.period_start_utc = g.target_time_utc AND wf.lead_days = g.wx_lead_days
LEFT JOIN feat_weather wo
  ON wo.period_start_utc = g.target_time_utc AND wo.lead_days = 0
ORDER BY g.origin_time_utc, g.horizon_h;
