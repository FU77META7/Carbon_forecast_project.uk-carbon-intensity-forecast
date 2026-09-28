"""Naive baselines. Each is a column already computed, leak-free, in training_set.

* persistence          - latest published actual at the origin (period ending
                         origin - 60 min), held flat for every horizon.
* seasonal_naive_day   - same time of day on the most recent day already
                         published at the origin: 2 days before the target for
                         h <= 46.5h, 3 days for longer horizons. A literal
                         "24h ago" value does not exist yet at a 24-48h horizon.
* seasonal_naive_week  - same half-hour one week before the target.
* neso_stored_forecast - NESO's forecast as stored by the Carbon Intensity API.
                         NOT like-for-like: the stored value is a short-lead
                         nowcast (its MAE matches ~1h persistence), not a
                         24-48h-ahead forecast. Reported as a reference only.
"""

import pandas as pd

BASELINE_SOURCES = {
    "persistence": "f_intensity_latest",
    "seasonal_naive_day": "f_intensity_target_seasonal_day",
    "seasonal_naive_week": "f_intensity_target_minus_168h",
    "neso_stored_forecast": "ref_neso_forecast_gco2",
}
# Baselines computable at the origin for a genuine 24-48h forecast.
FAIR_BASELINES = ("persistence", "seasonal_naive_day", "seasonal_naive_week")


def predict_baselines(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({name: df[col] for name, col in BASELINE_SOURCES.items()}, index=df.index)
