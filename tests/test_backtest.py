from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from carbon_forecast import backtest
from carbon_forecast.dataset import TARGET
from carbon_forecast.evaluate import add_context, coverage_table, pick_sample_week
from carbon_forecast.models.lgbm import LGBMForecaster
from tests.test_models import _frame

PARAMS = {"objective": "regression", "learning_rate": 0.1, "num_leaves": 7, "min_data_in_leaf": 20}
SETTINGS = {
    "evaluation": {"test_start": date(2024, 3, 1)},
    "model": {
        "seed": 1,
        "variants": {
            "no_weather": {"prefixes": ["f_"], "train_start": date(2024, 1, 1)},
            "weather_forecast": {"prefixes": ["f_", "wxf_"], "train_start": date(2024, 1, 15)},
            "oracle_weather": {
                "prefixes": ["f_", "oracle_"],
                "train_start": date(2024, 1, 1),
                "params_from": "no_weather",
                "leaky": True,
            },
        },
    },
}
TUNED = {v: {"params": PARAMS, "num_boost_round": 30} for v in ("no_weather", "weather_forecast")}


def test_month_starts():
    got = backtest.month_starts(datetime(2025, 10, 1), datetime(2026, 1, 15, 18))
    assert got == [
        datetime(2025, 10, 1),
        datetime(2025, 11, 1),
        datetime(2025, 12, 1),
        datetime(2026, 1, 1),
        datetime(2026, 2, 1),
    ]


def test_every_fold_trains_only_on_the_past(monkeypatch):
    df = _frame(n_origins=4 * 120)  # 2024-01-01 .. ~2024-04-30, every 6h
    seen = []
    real_fit = LGBMForecaster.fit

    def spy(self, train, *a, **k):
        seen.append((train["origin_time_utc"].min(), train["target_time_utc"].max(), self.params))
        return real_fit(self, train, *a, **k)

    monkeypatch.setattr(LGBMForecaster, "fit", spy)
    results, importance = backtest.run_backtest(df, SETTINGS, TUNED)

    folds = sorted(results["fold_start_utc"].unique())
    assert [pd.Timestamp(f) for f in folds] == [
        pd.Timestamp("2024-03-01"),
        pd.Timestamp("2024-04-01"),
    ]
    # 3 point models + 2 quantile models per fold
    assert len(seen) == 2 * 5
    fold_of_fit = np.repeat(folds, 5)
    for (min_origin, max_target, _), fold in zip(seen, fold_of_fit, strict=True):
        assert max_target < pd.Timestamp(fold)
        assert min_origin >= pd.Timestamp("2024-01-01")
    # the weather model honours its later train_start
    wf_fits = [s for s in seen if "alpha" not in s[2]][1::3]
    assert all(min_origin >= pd.Timestamp("2024-01-15") for min_origin, _, _ in wf_fits)

    test_rows = df[df["origin_time_utc"] >= datetime(2024, 3, 1)]
    assert len(results) == len(test_rows)
    for col in (
        "no_weather",
        "weather_forecast",
        "oracle_weather",
        "weather_forecast_p10",
        "weather_forecast_p90",
        "persistence",
    ):
        assert results[col].notna().all(), col
    assert (results["weather_forecast_p10"] <= results["weather_forecast_p90"]).all()
    assert set(importance["model"]) == {"weather_forecast", "no_weather"}


def test_wind_terciles_and_seasons():
    df = pd.DataFrame(
        {
            "target_time_utc": pd.date_range("2025-01-01", periods=9, freq="30min"),
            "target_actual_wind_pct": [10, 20, 30, 40, 50, 60, 70, 80, 90],
            "target_month": [1, 4, 7, 10, 12, 2, 5, 8, 11],
            "target_local_hour": [0, 5.5, 6, 11.5, 12, 17.5, 18, 23.5, 3],
        }
    )
    out, (lo, hi) = add_context(df)
    assert list(out["wind_regime"]) == ["low"] * 3 + ["medium"] * 3 + ["high"] * 3
    assert out["season"].tolist()[:4] == [
        "Winter (DJF)",
        "Spring (MAM)",
        "Summer (JJA)",
        "Autumn (SON)",
    ]
    assert out["time_of_day"].tolist()[:8] == [
        "00-06",
        "00-06",
        "06-12",
        "06-12",
        "12-18",
        "12-18",
        "18-24",
        "18-24",
    ]


def test_coverage_table_math():
    df = pd.DataFrame(
        {
            "horizon_h": [24.0, 24.0, 30.0, 47.5],
            TARGET: [10.0, 20.0, 30.0, 40.0],
            "weather_forecast_p10": [5.0, 25.0, 25.0, 30.0],
            "weather_forecast_p90": [15.0, 30.0, 28.0, 50.0],
        }
    )
    cov = coverage_table(df).set_index("horizons")
    assert cov.loc["all horizons", "coverage_%"] == pytest.approx(50.0)
    assert cov.loc["all horizons", "below_p10_%"] == pytest.approx(25.0)
    assert cov.loc["all horizons", "above_p90_%"] == pytest.approx(25.0)
    assert cov.loc["all horizons", "mean_width"] == pytest.approx((10 + 5 + 3 + 20) / 4)


def test_sample_week_is_a_complete_week_of_day_ahead_forecasts():
    origins = pd.date_range("2025-06-01 12:00", "2025-07-15 12:00", freq="D")
    rows = []
    rng = np.random.default_rng(0)
    for o in origins:
        for h in np.arange(24, 48.5, 0.5):
            rows.append(
                {
                    "origin_time_utc": o,
                    "horizon_h": h,
                    "target_time_utc": o + pd.Timedelta(hours=h),
                    TARGET: 100.0,
                    "weather_forecast": 100 + rng.normal(0, 10),
                }
            )
    week = pick_sample_week(pd.DataFrame(rows))
    assert len(week) == 7 * 48
    assert week["target_time_utc"].is_unique
    assert (week["horizon_h"] < 48).all()
    assert week["target_time_utc"].iloc[0].dayofweek == 0  # starts on a Monday
