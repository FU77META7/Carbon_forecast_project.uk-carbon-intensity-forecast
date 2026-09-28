from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from carbon_forecast.dataset import TARGET, feature_columns, time_split
from carbon_forecast.evaluate import mape, score, score_table, skill
from carbon_forecast.models.baselines import BASELINE_SOURCES, predict_baselines
from carbon_forecast.models.lgbm import LGBMForecaster, quantile_params
from carbon_forecast.models.tune import month_offset, sample_configs


def _frame(n_origins: int = 60, seed: int = 0) -> pd.DataFrame:
    """Synthetic training_set-shaped frame: y depends on two features + noise."""
    rng = np.random.default_rng(seed)
    t0 = datetime(2024, 1, 1)
    rows = []
    for i in range(n_origins):
        origin = t0 + timedelta(hours=6 * i)
        for h in (24.0, 36.0, 48.0):
            a, w = rng.normal(150, 30), rng.uniform(0, 1)
            rows.append(
                {
                    "origin_time_utc": origin,
                    "horizon_h": h,
                    "target_time_utc": origin + timedelta(hours=h),
                    "f_intensity_latest": a,
                    "f_intensity_target_seasonal_day": a + 5,
                    "f_intensity_target_minus_168h": a - 5,
                    "f_horizon_h": h,
                    "wxf_wind_power_frac_mean": w,
                    "oracle_wind_power_frac_mean": w,
                    "ref_neso_forecast_gco2": a,
                    "asof_history_utc": origin,
                    TARGET: 0.5 * a - 80 * w + 100 + rng.normal(0, 3),
                }
            )
    return pd.DataFrame(rows)


def test_metrics_known_values():
    y, p = np.array([100.0, 200.0, 0.0]), np.array([110.0, 180.0, 5.0])
    assert score(y, p)["mae"] == pytest.approx((10 + 20 + 5) / 3)
    assert score(y, p)["rmse"] == pytest.approx(np.sqrt((100 + 400 + 25) / 3))
    assert mape(y, p) == pytest.approx((0.10 + 0.10) / 2 * 100)  # zero actual excluded
    assert skill(30.0, 40.0) == pytest.approx(0.25)


def test_score_table_uses_common_rows_only():
    df = pd.DataFrame({"y": [1.0, 2.0, 3.0], "a": [1.0, np.nan, 3.0], "b": [2.0, 2.0, 2.0]})
    t = score_table(df, "y", ["a", "b"])
    assert t.loc["a", "n"] == t.loc["b", "n"] == 2


def test_baselines_are_the_documented_columns():
    df = _frame(5)
    preds = predict_baselines(df)
    assert list(preds.columns) == list(BASELINE_SOURCES)
    for name, col in BASELINE_SOURCES.items():
        assert preds[name].equals(df[col])


def test_feature_selection_guards():
    df = _frame(3)
    assert "f_horizon_h" in feature_columns(df, ["f_"])
    with pytest.raises(ValueError, match="never"):
        feature_columns(df, ["ref_"])
    with pytest.raises(ValueError, match="never"):
        feature_columns(df, ["asof_"])
    with pytest.raises(ValueError, match="leaky"):
        feature_columns(df, ["oracle_"])
    assert feature_columns(df, ["oracle_"], allow_leaky=True) == ["oracle_wind_power_frac_mean"]
    with pytest.raises(ValueError):
        LGBMForecaster(["f_horizon_h", TARGET], {}, 10)
    with pytest.raises(ValueError, match="leaky"):
        LGBMForecaster(["oracle_wind_power_frac_mean"], {}, 10)


def test_time_split_purges_straddling_targets():
    df = _frame(60)
    boundary = datetime(2024, 1, 10)
    train, test = time_split(df, boundary)
    assert (train["target_time_utc"] < boundary).all()
    assert (test["origin_time_utc"] >= boundary).all()
    # Origins in the last 48h before the boundary have targets after it: purged.
    assert train["origin_time_utc"].max() <= boundary - timedelta(hours=24)
    assert len(train) + len(test) < len(df)


def test_lgbm_learns_and_quantiles_bracket_the_median():
    df = _frame(1500)
    train, test = time_split(df, df["origin_time_utc"].quantile(0.75))
    feats = feature_columns(df, ["f_", "wxf_"])
    # Regularised on purpose: on small data, loosely regularised quantile models
    # fit the noise and their 10-90% band covers well under 80% out of sample.
    params = {
        "objective": "regression",
        "learning_rate": 0.1,
        "num_leaves": 7,
        "min_data_in_leaf": 50,
    }
    model = LGBMForecaster(feats, params, 100).fit(train)
    mae_model = score(test[TARGET], model.predict(test))["mae"]
    mae_persist = score(test[TARGET], test["f_intensity_latest"])["mae"]
    assert mae_model < 0.5 * mae_persist
    assert model.feature_importance().index[0] in ("wxf_wind_power_frac_mean", "f_intensity_latest")
    lo = LGBMForecaster(feats, quantile_params(params, 0.1), 100).fit(train).predict(test)
    hi = LGBMForecaster(feats, quantile_params(params, 0.9), 100).fit(train).predict(test)
    assert np.mean(lo < hi) > 0.95
    coverage = np.mean((test[TARGET] >= lo) & (test[TARGET] <= hi))
    assert 0.65 < coverage < 0.9  # nominal 0.8


def test_training_is_deterministic():
    df = _frame(100)
    feats = feature_columns(df, ["f_"])
    params = {
        "objective": "regression",
        "bagging_fraction": 0.7,
        "bagging_freq": 1,
        "feature_fraction": 0.8,
        "min_data_in_leaf": 10,
    }
    a = LGBMForecaster(feats, params, 50, seed=7).fit(df).predict(df)
    b = LGBMForecaster(feats, params, 50, seed=7).fit(df).predict(df)
    assert np.array_equal(a, b)


def test_search_space_sampling_and_month_offsets():
    configs = sample_configs(12, seed=42)
    assert len(configs) == 12 and len({str(c) for c in configs}) == 12
    assert configs == sample_configs(12, seed=42)
    assert month_offset(datetime(2025, 10, 1), -6) == datetime(2025, 4, 1)
    assert month_offset(datetime(2025, 2, 1), -3) == datetime(2024, 11, 1)
