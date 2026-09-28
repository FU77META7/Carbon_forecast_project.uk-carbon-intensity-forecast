"""Rolling-origin backtest: expanding window, retrained monthly.

python -m carbon_forecast.backtest

For each calendar month from evaluation.test_start to the end of the data:
train every model variant on all rows whose TARGET is before the month starts
(expanding window, purged at the boundary), then forecast every origin in the
month. Hyperparameters are the ones tuned on the earlier validation block and
stay fixed. Results land in DuckDB (`backtest_results`,
`backtest_feature_importance`, `backtest_interval_calibration`) for the
evaluation report and the app.
"""

import argparse
import logging
import time
from datetime import datetime

import duckdb
import numpy as np
import pandas as pd

from carbon_forecast.config import load_settings, resolve
from carbon_forecast.dataset import KEYS, TARGET, feature_columns, load_training_set
from carbon_forecast.db import connect
from carbon_forecast.models.baselines import predict_baselines
from carbon_forecast.models.conformal import calibrate
from carbon_forecast.models.lgbm import LGBMForecaster, load_tuned, quantile_params, variant_spec
from carbon_forecast.models.tune import month_offset

log = logging.getLogger(__name__)

# Prediction intervals (10th-90th percentile) for the deployable weather model:
# raw quantile LightGBM (p10/p90) and conformalized (cp10/cp90).
INTERVAL_VARIANTS = ("weather_forecast",)
QUANTILES = {"p10": 0.1, "p90": 0.9}
# Feature attributions are computed for the final fold's models.
IMPORTANCE_VARIANTS = ("weather_forecast", "no_weather")


def month_starts(first: datetime, last_origin: datetime) -> list[datetime]:
    """Fold boundaries: first, first + 1 month, ... up to just past last_origin."""
    out = [first]
    while out[-1] <= last_origin:
        out.append(month_offset(out[-1], 1))
    return out


def run_backtest(
    df: pd.DataFrame, settings: dict, tuned: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    m = settings["model"]
    test_start = datetime.combine(settings["evaluation"]["test_start"], datetime.min.time())
    bounds = month_starts(test_start, df["origin_time_utc"].max())
    test_all = df[df["origin_time_utc"] >= test_start]
    results = pd.concat([test_all[KEYS + [TARGET]], predict_baselines(test_all)], axis=1)
    results["fold_start_utc"] = pd.NaT
    importances, calibration = [], []

    for fold_start, fold_end in zip(bounds, bounds[1:], strict=False):
        in_fold = (df["origin_time_utc"] >= fold_start) & (df["origin_time_utc"] < fold_end)
        test = df[in_fold]
        if test.empty:
            continue
        results.loc[test.index, "fold_start_utc"] = fold_start
        for variant in m["variants"]:
            spec = variant_spec(variant, settings, tuned)
            start = datetime.combine(spec["train_start"], datetime.min.time())
            train = df[(df["target_time_utc"] < fold_start) & (df["origin_time_utc"] >= start)]
            feats = feature_columns(df, spec["prefixes"], allow_leaky=spec["leaky"])
            t0 = time.time()
            model = LGBMForecaster(
                feats,
                spec["params"],
                spec["num_boost_round"],
                seed=m["seed"],
                allow_leaky=spec["leaky"],
            ).fit(train)
            results.loc[test.index, variant] = model.predict(test)
            if variant in INTERVAL_VARIANTS:
                calibration.append(
                    _intervals(df, results, test, train, feats, spec, variant, fold_start, settings)
                )
            if variant in IMPORTANCE_VARIANTS and fold_end == bounds[-1]:
                importances.append(_importance(model, test, variant, fold_start))
            log.info(
                "fold %s %-17s train %7d rows, test %5d rows (%.1fs)",
                f"{fold_start:%Y-%m}",
                variant,
                len(train),
                len(test),
                time.time() - t0,
            )

    return results, pd.concat(importances, ignore_index=True), pd.DataFrame(calibration)


def _sorted_band(lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """Repair quantile crossing (p10 > p90) by sorting the pair; returns the count."""
    return np.minimum(lo, hi), np.maximum(lo, hi), int((lo > hi).sum())


def _intervals(df, results, test, train, feats, spec, variant, fold_start, settings) -> dict:
    """Quantile models trained on targets before the calibration window, scored on
    that window (strictly before the fold), then conformalized for the fold."""
    ev, seed = settings["evaluation"], settings["model"]["seed"]
    cal_start = month_offset(fold_start, -ev["calibration_months"])
    q_train = train[train["target_time_utc"] < cal_start]
    cal = train[train["origin_time_utc"] >= cal_start]  # targets already < fold_start
    band = {}
    for name, alpha in QUANTILES.items():
        q = LGBMForecaster(
            feats, quantile_params(spec["params"], alpha), spec["num_boost_round"], seed=seed
        ).fit(q_train)
        band[name] = (q.predict(cal), q.predict(test))
    lo_cal, hi_cal, _ = _sorted_band(band["p10"][0], band["p90"][0])
    lo, hi, crossed = _sorted_band(band["p10"][1], band["p90"][1])
    qhat = calibrate(cal[TARGET].to_numpy(), lo_cal, hi_cal, ev["interval_alpha"])
    results.loc[test.index, f"{variant}_p10"] = lo
    results.loc[test.index, f"{variant}_p90"] = hi
    results.loc[test.index, f"{variant}_cp10"] = lo - qhat
    results.loc[test.index, f"{variant}_cp90"] = hi + qhat
    y_cal = cal[TARGET].to_numpy()
    return {
        "fold_start_utc": fold_start,
        "model": variant,
        "calibration_start_utc": cal_start,
        "n_calibration": len(cal),
        "calibration_raw_coverage": float(np.mean((y_cal >= lo_cal) & (y_cal <= hi_cal))),
        "conformal_adjustment": qhat,
        "test_rows_crossed": crossed,
    }


def _importance(model: LGBMForecaster, test: pd.DataFrame, variant: str, fold: datetime):
    """Mean |SHAP| (LightGBM's built-in TreeSHAP) on the fold's test rows, plus gain."""
    contrib = model.booster.predict(
        test[model.features], num_iteration=model.best_iteration, pred_contrib=True
    )[:, :-1]  # last column is the expected value
    gain = model.feature_importance("gain")
    return pd.DataFrame(
        {
            "model": variant,
            "fold_start_utc": fold,
            "feature": model.features,
            "mean_abs_shap": np.abs(contrib).mean(axis=0),
            "gain": gain.reindex(model.features).to_numpy(),
        }
    )


def save(
    con: duckdb.DuckDBPyConnection,
    results: pd.DataFrame,
    importance: pd.DataFrame,
    calibration: pd.DataFrame,
):
    """Store results with the context the error breakdowns need."""
    con.register("results_df", results)
    con.register("importance_df", importance)
    con.register("calibration_df", calibration)
    con.execute(
        "CREATE OR REPLACE TABLE backtest_interval_calibration AS SELECT * FROM calibration_df"
    )
    con.unregister("calibration_df")
    con.execute("""
        CREATE OR REPLACE TABLE backtest_results AS
        SELECT r.*,
               c.uk_date          AS target_uk_date,
               c.local_hour       AS target_local_hour,
               c.month            AS target_month,
               g.wind_pct         AS target_actual_wind_pct  -- outturn: for slicing errors only
        FROM results_df r
        JOIN calendar c ON c.period_start_utc = r.target_time_utc
        LEFT JOIN stg_generation g ON g.period_start_utc = r.target_time_utc
        ORDER BY r.origin_time_utc, r.horizon_h
    """)
    con.execute(
        "CREATE OR REPLACE TABLE backtest_feature_importance AS SELECT * FROM importance_df"
    )
    con.unregister("results_df")
    con.unregister("importance_df")


def main(argv: list[str] | None = None) -> None:
    settings = load_settings()
    p = argparse.ArgumentParser(prog="python -m carbon_forecast.backtest")
    p.add_argument("--db", default=settings["db_path"])
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    tuned = load_tuned()
    with connect(resolve(args.db)) as con:
        df = load_training_set(con)
        log.info("loaded %d labelled rows", len(df))
        results, importance, calibration = run_backtest(df, settings, tuned)
        save(con, results, importance, calibration)
        n = con.execute("SELECT count(*), count(DISTINCT fold_start_utc) FROM backtest_results")
        rows, folds = n.fetchone()
    log.info("backtest_results: %d rows over %d monthly folds", rows, folds)
    log.info("quantile crossings repaired in %d test rows", calibration["test_rows_crossed"].sum())


if __name__ == "__main__":
    main()
