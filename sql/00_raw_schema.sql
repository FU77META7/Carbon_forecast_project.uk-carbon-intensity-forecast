-- Raw landing tables. One row per source record, typed but otherwise untouched.
-- All timestamps are naive TIMESTAMPs holding UTC (the `_utc` suffix is the
-- contract). Primary keys make every ingest an idempotent upsert.

-- Carbon Intensity API, national, half-hourly.
CREATE TABLE IF NOT EXISTS raw_intensity (
    period_start_utc TIMESTAMP PRIMARY KEY,
    period_end_utc   TIMESTAMP NOT NULL,
    forecast_gco2    INTEGER,          -- NESO forecast (single stored vintage, lead time undocumented)
    actual_gco2      INTEGER,          -- outturn estimate; null for periods not yet settled
    intensity_index  VARCHAR,          -- very low / low / moderate / high / very high
    ingested_at_utc  TIMESTAMP NOT NULL
);

-- Carbon Intensity API generation mix, half-hourly, long format (one row per fuel).
-- Values are percentages of generation; the API does not publish MW.
CREATE TABLE IF NOT EXISTS raw_generation (
    period_start_utc TIMESTAMP NOT NULL,
    period_end_utc   TIMESTAMP NOT NULL,
    fuel             VARCHAR   NOT NULL,
    perc             DOUBLE,
    ingested_at_utc  TIMESTAMP NOT NULL,
    PRIMARY KEY (period_start_utc, fuel)
);

-- Weather sites, loaded from config/settings.yaml on every ingest.
CREATE TABLE IF NOT EXISTS raw_weather_locations (
    location_id VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    role        VARCHAR NOT NULL,      -- wind / solar / demand
    latitude    DOUBLE  NOT NULL,
    longitude   DOUBLE  NOT NULL
);

-- Open-Meteo hourly weather. Units: wind m/s, radiation W/m2 (mean over the
-- PRECEDING hour, so the 13:00 value describes 12:00-13:00), temperature degC,
-- cloud cover %.

-- Archive API: reanalysis / observed conditions. Leaky as a forecast feature.
CREATE TABLE IF NOT EXISTS raw_weather_archive (
    location_id         VARCHAR   NOT NULL,
    time_utc            TIMESTAMP NOT NULL,
    wind_speed_100m     DOUBLE,
    shortwave_radiation DOUBLE,
    temperature_2m      DOUBLE,
    cloud_cover         DOUBLE,
    ingested_at_utc     TIMESTAMP NOT NULL,
    PRIMARY KEY (location_id, time_utc)
);

-- Historical Forecast API: first hours of each model run stitched together.
-- Effectively a 0-6h forecast (and in earlier years a copy of archive values),
-- so NOT a leakage-free proxy for a 24-48h-ahead forecast. Kept for comparison only.
CREATE TABLE IF NOT EXISTS raw_weather_hist_forecast (
    location_id         VARCHAR   NOT NULL,
    time_utc            TIMESTAMP NOT NULL,
    wind_speed_100m     DOUBLE,
    shortwave_radiation DOUBLE,
    temperature_2m      DOUBLE,
    cloud_cover         DOUBLE,
    ingested_at_utc     TIMESTAMP NOT NULL,
    PRIMARY KEY (location_id, time_utc)
);

-- Previous Runs API: the value predicted `lead_days` * 24h before time_utc.
-- This is the source of leakage-free weather features.
CREATE TABLE IF NOT EXISTS raw_weather_prev_runs (
    location_id         VARCHAR   NOT NULL,
    time_utc            TIMESTAMP NOT NULL,
    lead_days           INTEGER   NOT NULL,
    wind_speed_100m     DOUBLE,
    shortwave_radiation DOUBLE,
    temperature_2m      DOUBLE,
    cloud_cover         DOUBLE,
    ingested_at_utc     TIMESTAMP NOT NULL,
    PRIMARY KEY (location_id, time_utc, lead_days)
);
