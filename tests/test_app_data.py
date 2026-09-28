from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from carbon_forecast import app_data
from carbon_forecast.db import connect


@pytest.fixture
def con():
    """A tiny backtest_results table: 10 days of origins every 6h, 49 horizons."""
    c = connect()
    rows = []
    for d in range(10):
        for hour in (0, 6, 12, 18):
            origin = datetime(2026, 1, 1) + timedelta(days=d, hours=hour)
            for h in np.arange(24, 48.5, 0.5):
                t = origin + timedelta(hours=float(h))
                y = 100 + (t.hour % 12)
                rows.append(
                    {
                        "origin_time_utc": origin,
                        "horizon_h": float(h),
                        "target_time_utc": t,
                        "y_actual_gco2": float(y),
                        "weather_forecast": y + 2.0,
                        "no_weather": y - 6.0,
                        "seasonal_naive_day": y + 10.0,
                        "weather_forecast_p10": y - 5.0,
                        "weather_forecast_p90": y + 5.0,
                        "weather_forecast_cp10": y - 8.0,
                        "weather_forecast_cp90": y + 1.0,
                    }
                )
    c.register("rows_df", pd.DataFrame(rows))
    c.execute("CREATE TABLE backtest_results AS SELECT * FROM rows_df")
    yield c
    c.close()


def test_day_ahead_covers_each_target_once(con):
    models = ["weather_forecast", "no_weather"]
    long, wide = app_data.day_ahead(con, date(2026, 1, 3), date(2026, 1, 5), 12, models)
    assert len(wide) == 3 * 48
    assert wide["target_time_utc"].is_unique
    assert (wide["origin_time_utc"].dt.hour == 12).all()
    assert wide["horizon_h"].between(24, 47.5).all()
    assert set(long["series"]) == {"y_actual_gco2", *models}
    assert len(long) == len(wide) * 3


def test_day_ahead_rejects_unknown_inputs(con):
    with pytest.raises(ValueError):
        app_data.day_ahead(con, date(2026, 1, 3), date(2026, 1, 4), 3, ["weather_forecast"])
    with pytest.raises(ValueError):
        app_data.day_ahead(con, date(2026, 1, 3), date(2026, 1, 4), 12, ["x; DROP TABLE t"])


def test_window_scores_and_coverage(con):
    _, wide = app_data.day_ahead(
        con, date(2026, 1, 3), date(2026, 1, 4), 12, ["weather_forecast", "no_weather"]
    )
    s = app_data.window_scores(wide, ["weather_forecast", "no_weather"]).set_index("model")
    assert s.loc["LightGBM + weather forecast", "MAE (gCO2/kWh)"] == pytest.approx(2.0)
    assert s.loc["LightGBM, no weather", "bias (gCO2/kWh)"] == pytest.approx(-6.0)
    assert app_data.window_coverage(wide) == pytest.approx(1.0)


def test_missing_tables_reported(con):
    assert set(app_data.missing_tables(con)) == {
        "backtest_metrics_by_horizon",
        "backtest_metrics_overall",
        "backtest_interval_coverage",
    }
