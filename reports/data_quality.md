# Data quality report

Generated 2026-09-28 14:14 UTC by `python -m carbon_forecast.quality`. All timestamps are UTC.
Expected slots run from the configured start of each series to its latest stored timestamp, on a 30-minute (Carbon Intensity) or hourly (weather) grid.

## Coverage, gaps, duplicates and nulls

| series | rows | first | last | expected slots | missing slots | gap ranges | duplicate keys | nulls |
|---|---|---|---|---|---|---|---|---|
| intensity | 135,517 | 2019-01-01 00:00:00 | 2026-09-27 23:30:00 | 135,696 | 179 | 5 | 0 | forecast_gco2=43, actual_gco2=579 |
| generation | 1,219,698 | 2019-01-01 00:00:00 | 2026-09-27 23:30:00 | 135,696 | 174 | 5 | 0 | 0 |
| archive/east_anglia | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| archive/hornsea | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| archive/london | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| archive/moray_firth | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| archive/somerset | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| archive/whitelee | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| hist_forecast/east_anglia | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| hist_forecast/hornsea | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| hist_forecast/london | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| hist_forecast/moray_firth | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| hist_forecast/somerset | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| hist_forecast/whitelee | 67,848 | 2019-01-01 00:00:00 | 2026-09-27 23:00:00 | 67,848 | 0 | 0 | 0 | 0 |
| prev_runs_d1/east_anglia | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | 0 |
| prev_runs_d1/hornsea | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | 0 |
| prev_runs_d1/london | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | 0 |
| prev_runs_d1/moray_firth | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | 0 |
| prev_runs_d1/somerset | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | 0 |
| prev_runs_d1/whitelee | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | 0 |
| prev_runs_d2/east_anglia | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |
| prev_runs_d2/hornsea | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |
| prev_runs_d2/london | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |
| prev_runs_d2/moray_firth | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |
| prev_runs_d2/somerset | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |
| prev_runs_d2/whitelee | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |
| prev_runs_d3/east_anglia | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |
| prev_runs_d3/hornsea | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |
| prev_runs_d3/london | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |
| prev_runs_d3/moray_firth | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |
| prev_runs_d3/somerset | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |
| prev_runs_d3/whitelee | 22,392 | 2024-03-09 00:00:00 | 2026-09-27 23:00:00 | 22,392 | 0 | 0 | 0 | cloud_cover=129 |

## Gaps (largest 10 per series)

**intensity**: 5 gap range(s)

| first missing | last missing | slots |
|---|---|---|
| 2023-10-20 22:00:00 | 2023-10-22 19:00:00 | 91 |
| 2021-12-26 15:00:00 | 2021-12-27 17:30:00 | 54 |
| 2024-06-11 23:00:00 | 2024-06-12 14:00:00 | 31 |
| 2021-04-19 22:00:00 | 2021-04-19 22:30:00 | 2 |
| 2021-04-19 17:00:00 | 2021-04-19 17:00:00 | 1 |

**generation**: 5 gap range(s)

| first missing | last missing | slots |
|---|---|---|
| 2023-10-20 22:00:00 | 2023-10-22 14:30:00 | 82 |
| 2021-12-26 15:00:00 | 2021-12-27 13:00:00 | 45 |
| 2024-06-11 23:00:00 | 2024-06-12 09:30:00 | 22 |
| 2025-01-12 23:00:00 | 2025-01-13 07:00:00 | 17 |
| 2025-08-10 23:00:00 | 2025-08-11 02:30:00 | 8 |


## UK daylight-saving transitions (intensity)

Settlement periods per UK local day. Clock-change days must have 46 (spring) or 50 (autumn) periods.

- Complete UK local days checked: 2,825
- Days whose period count differs from the calendar: 6

| UK date | periods stored | periods expected | ok |
|---|---|---|---|
| 2019-03-31 | 46 | 46 | yes |
| 2019-10-27 | 50 | 50 | yes |
| 2020-03-29 | 46 | 46 | yes |
| 2020-10-25 | 50 | 50 | yes |
| 2021-03-28 | 46 | 46 | yes |
| 2021-10-31 | 50 | 50 | yes |
| 2022-03-27 | 46 | 46 | yes |
| 2022-10-30 | 50 | 50 | yes |
| 2023-03-26 | 46 | 46 | yes |
| 2023-10-29 | 50 | 50 | yes |
| 2024-03-31 | 46 | 46 | yes |
| 2024-10-27 | 50 | 50 | yes |
| 2025-03-30 | 46 | 46 | yes |
| 2025-10-26 | 50 | 50 | yes |
| 2026-03-29 | 46 | 46 | yes |

Mismatched days (first 20):

| UK date | periods stored | periods expected |
|---|---|---|
| 2021-04-19 | 45 | 48 |
| 2021-12-26 | 30 | 48 |
| 2021-12-27 | 12 | 48 |
| 2023-10-20 | 46 | 48 |
| 2023-10-22 | 7 | 48 |
| 2024-06-12 | 17 | 48 |

## Value sanity

Intensity (gCO2/kWh):

|  | min | max | mean |
|---|---|---|---|
| actual | 0 | 447 | 162.82 |
| forecast | 5 | 13,579 | 162.30 |

Negative values: 0

Suspect intensity values (> 1,000 or exactly 0): 12

| period start | forecast | actual | reason |
|---|---|---|---|
| 2019-01-10 00:30:00 | 9,899 | 287 | forecast > 1000 |
| 2019-02-16 11:30:00 | 1,587 | 178 | forecast > 1000 |
| 2019-02-16 17:30:00 | 4,385 | 206 | forecast > 1000 |
| 2019-05-26 21:00:00 | 1,707 | 118 | forecast > 1000 |
| 2019-07-24 21:00:00 | 13,579 | 304 | forecast > 1000 |
| 2019-07-24 22:00:00 | 11,513 | 279 | forecast > 1000 |
| 2023-01-31 01:00:00 | 89 | 0 | actual = 0 |
| 2023-06-07 09:30:00 | 185 | 0 | actual = 0 |
| 2023-06-07 10:00:00 | 176 | 0 | actual = 0 |
| 2023-06-07 10:30:00 | 170 | 0 | actual = 0 |
| 2023-06-07 11:00:00 | 164 | 0 | actual = 0 |
| 2026-08-06 11:00:00 | 62 | 0 | actual = 0 |

Generation mix:

- Fuels: biomass (135,522), coal (135,522), gas (135,522), hydro (135,522), imports (135,522), nuclear (135,522), other (135,522), solar (135,522), wind (135,522)
- Fuels per period: min 9, max 9
- Sum of percentages per period: min 99.7, max 100.3; periods outside 95-105%: 0

## Weather: historical-forecast vs archive

The Historical Forecast API stitches together the first hours of each model run, so at best it is a ~0-6h forecast. Where it is *identical* to the archive (observed conditions), it is returning outturn weather outright. Either way it would leak into a 24-48h model; leakage-free weather comes from the Previous Runs API instead. % of hours identical, all locations:

| year | overlapping hours | wind_speed_100m % identical | shortwave_radiation % identical | temperature_2m % identical | cloud_cover % identical | wind 100m MAE (m/s) |
|---|---|---|---|---|---|---|
| 2019 | 52,560 | 100.00 | 100.00 | 100.00 | 100.00 | 0.00 |
| 2020 | 52,704 | 100.00 | 100.00 | 100.00 | 100.00 | 0.00 |
| 2021 | 52,560 | 100.00 | 100.00 | 100.00 | 100.00 | 0.00 |
| 2022 | 52,560 | 100.00 | 52.33 | 21.16 | 40.63 | 0.00 |
| 2023 | 52,560 | 100.00 | 46.00 | 5.92 | 32.41 | 0.00 |
| 2024 | 52,704 | 60.52 | 46.03 | 6.30 | 33.08 | 0.46 |
| 2025 | 52,560 | 0.33 | 45.81 | 6.36 | 29.84 | 1.17 |
| 2026 | 38,880 | 0.32 | 42.97 | 6.19 | 34.07 | 1.11 |
