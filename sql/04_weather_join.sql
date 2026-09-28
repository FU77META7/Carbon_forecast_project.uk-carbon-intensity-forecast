-- Layer 4: weather aligned to half-hour settlement periods, aggregated by site role.
-- One row per (period_start_utc, lead_days): lead_days = 0 is observed weather
-- (archive, leaky as a forecast input), 1..3 are forecasts made that many days
-- before the valid time (previous-runs API).
--
-- Alignment from hourly to half-hourly, for the period [P, P+30min):
--   * instantaneous variables (wind, temperature, cloud cover) are linearly
--     interpolated to the period midpoint P+15min between the hour at or before
--     P (h0) and the next hour (h1): weight 0.25 on h1 for :00 periods, 0.75 for :30.
--   * shortwave radiation is Open-Meteo's mean over the PRECEDING hour, so the
--     value stamped h1 = h0 + 1h is the mean over [h0, h1), which contains P.

CREATE OR REPLACE TABLE feat_weather AS
WITH periods AS (
    SELECT
        period_start_utc,
        date_trunc('hour', period_start_utc) AS h0,
        CASE WHEN minute(period_start_utc) = 0 THEN 0.25 ELSE 0.75 END AS w1
    FROM calendar
),
aligned AS (
    SELECT
        p.period_start_utc,
        a.lead_days,
        a.location_id,
        (1 - p.w1) * a.wind_speed_100m + p.w1 * b.wind_speed_100m AS wind_speed_100m,
        (1 - p.w1) * a.temperature_2m  + p.w1 * b.temperature_2m  AS temperature_2m,
        (1 - p.w1) * a.cloud_cover     + p.w1 * b.cloud_cover     AS cloud_cover,
        b.shortwave_radiation                                      AS shortwave_radiation
    FROM periods p
    JOIN stg_weather_hourly a
      ON a.time_utc = p.h0
    JOIN stg_weather_hourly b
      ON b.time_utc = p.h0 + INTERVAL 1 HOUR
     AND b.location_id = a.location_id
     AND b.lead_days = a.lead_days
),
with_power AS (
    SELECT
        al.*,
        l.role,
        CASE
            WHEN al.wind_speed_100m < getvariable('wind_cut_in_ms')
              OR al.wind_speed_100m >= getvariable('wind_cut_out_ms') THEN 0.0
            WHEN al.wind_speed_100m >= getvariable('wind_rated_ms') THEN 1.0
            ELSE (pow(al.wind_speed_100m, 3) - pow(getvariable('wind_cut_in_ms'), 3))
               / (pow(getvariable('wind_rated_ms'), 3) - pow(getvariable('wind_cut_in_ms'), 3))
        END AS wind_power_frac
    FROM aligned al
    JOIN raw_weather_locations l USING (location_id)
)
-- Averages use ORDER BY location_id: a parallel avg() adds values in whatever
-- order threads finish, so the last bits of the result can differ between
-- builds, and LightGBM can then pick different split points. A fixed order makes
-- the features, and therefore the model, bit-for-bit reproducible.
SELECT
    period_start_utc,
    lead_days,
    avg(wind_speed_100m ORDER BY location_id)     FILTER (WHERE role = 'wind')   AS wind_speed_100m_mean,
    min(wind_speed_100m)                          FILTER (WHERE role = 'wind')   AS wind_speed_100m_min,
    max(wind_speed_100m)                          FILTER (WHERE role = 'wind')   AS wind_speed_100m_max,
    avg(wind_power_frac ORDER BY location_id)     FILTER (WHERE role = 'wind')   AS wind_power_frac_mean,
    avg(shortwave_radiation ORDER BY location_id) FILTER (WHERE role = 'solar')  AS solar_radiation_mean,
    avg(cloud_cover ORDER BY location_id)         FILTER (WHERE role = 'solar')  AS solar_cloud_cover_mean,
    avg(temperature_2m ORDER BY location_id)      FILTER (WHERE role = 'demand') AS demand_temperature,
    count(DISTINCT location_id)                             AS n_locations
FROM with_power
GROUP BY period_start_utc, lead_days
ORDER BY period_start_utc, lead_days;
