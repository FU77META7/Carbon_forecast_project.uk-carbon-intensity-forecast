-- Layer 1: staging. Typed, cleaned views over the raw landing tables.
-- Session variables are set by carbon_forecast.features from config/settings.yaml.

-- Intensity: impossible values become NULL but stay flagged for auditing.
CREATE OR REPLACE VIEW stg_intensity AS
WITH flagged AS (
    SELECT
        period_start_utc,
        actual_gco2,
        forecast_gco2,
        actual_gco2 = 0 OR actual_gco2 > getvariable('suspect_max_gco2') AS actual_is_suspect,
        forecast_gco2 = 0 OR forecast_gco2 > getvariable('suspect_max_gco2') AS forecast_is_suspect
    FROM raw_intensity
)
SELECT
    period_start_utc,
    CASE WHEN actual_is_suspect THEN NULL ELSE actual_gco2 END::DOUBLE AS actual_gco2,
    CASE WHEN forecast_is_suspect THEN NULL ELSE forecast_gco2 END::DOUBLE AS forecast_gco2,
    coalesce(actual_is_suspect, FALSE) AS actual_is_suspect,
    coalesce(forecast_is_suspect, FALSE) AS forecast_is_suspect
FROM flagged;

-- Generation mix: long (one row per fuel) to wide (one row per half-hour).
-- Conditional aggregation rather than dynamic PIVOT keeps the column set fixed
-- even if the API adds a fuel.
CREATE OR REPLACE VIEW stg_generation AS
SELECT
    period_start_utc,
    max(perc) FILTER (WHERE fuel = 'gas')     AS gas_pct,
    max(perc) FILTER (WHERE fuel = 'coal')    AS coal_pct,
    max(perc) FILTER (WHERE fuel = 'nuclear') AS nuclear_pct,
    max(perc) FILTER (WHERE fuel = 'wind')    AS wind_pct,
    max(perc) FILTER (WHERE fuel = 'solar')   AS solar_pct,
    max(perc) FILTER (WHERE fuel = 'hydro')   AS hydro_pct,
    max(perc) FILTER (WHERE fuel = 'biomass') AS biomass_pct,
    max(perc) FILTER (WHERE fuel = 'imports') AS imports_pct,
    max(perc) FILTER (WHERE fuel = 'other')   AS other_pct
FROM raw_generation
GROUP BY period_start_utc;

-- Hourly weather in one long relation. lead_days = 0 marks archive (observed)
-- values; 1..3 are previous-runs forecasts made that many days before.
CREATE OR REPLACE VIEW stg_weather_hourly AS
SELECT 0 AS lead_days, location_id, time_utc,
       wind_speed_100m, shortwave_radiation, temperature_2m, cloud_cover
FROM raw_weather_archive
UNION ALL
SELECT lead_days, location_id, time_utc,
       wind_speed_100m, shortwave_radiation, temperature_2m, cloud_cover
FROM raw_weather_prev_runs;
