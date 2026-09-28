"""Rolling-origin backtest: expanding window, retrained monthly.

python -m carbon_forecast.backtest

For each calendar month from evaluation.test_start to the end of the data:
train every model variant on all rows whose TARGET is before the month starts
(expanding window, purged at the boundary), then forecast every origin in the
month. Hyperparameters are the ones tuned on the earlier validation block and
stay fixed. Results land in DuckDB (`backtest_results`,
`backtest_feature_importance`) for the evaluation report and the app.
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
from carbon_forecast.models.lgbm import LGBMForecaster, load_tuned, quantile_params, variant_spec
from carbon_forecast.models.tune import month_offset

log = logging.getLogger(__name__)

# Prediction intervals (10th-90th percentile) for the deployable weather model.
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
    importances = []

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
                for name, alpha in QUANTILES.items():
                    q = LGBMForecaster(
                        feats,
                        quantile_params(spec["params"], alpha),
                        spec["num_boost_round"],
                        seed=m["seed"],
                    ).fit(train)
                    results.loc[test.index, f"{variant}_{name}"] = q.predict(test)
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

    # A p10 above the p90 (quantile crossing) is repaired by sorting the pair.
    for v in INTERVAL_VARIANTS:
        lo, hi = results[f"{v}_p10"], results[f"{v}_p90"]
        log.info("%s: p10 > p90 in %d of %d rows before repair", v, int((lo > hi).sum()), len(lo))
        results[f"{v}_p10"], results[f"{v}_p90"] = np.minimum(lo, hi), np.maximum(lo, hi)
    return results, pd.concat(importances, ignore_index=True)


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


def save(con: duckdb.DuckDBPyConnection, results: pd.DataFrame, importance: pd.DataFrame):
    """Store results with the context the error breakdowns need."""
    con.register("results_df", results)
    con.register("importance_df", importance)
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
        results, importance = run_backtest(df, settings, tuned)
        save(con, results, importance)
        n = con.execute("SELECT count(*), count(DISTINCT fold_start_utc) FROM backtest_results")
        rows, folds = n.fetchone()
    log.info("backtest_results: %d rows over %d monthly folds", rows, folds)


if __name__ == "__main__":
    main()
