"""LightGBM direct multi-horizon forecaster.

Strategy: ONE global model with the horizon as a feature (f_horizon_h), rather
than one model per horizon or horizon bucket. Reasons:
  * the 49 horizons share almost all structure (same origin features, same
    target-time calendar); a global model sees 49x more rows than any
    per-horizon model and learns how the influence of recent history decays
    with horizon, instead of relearning it 49 times;
  * predictions vary smoothly across horizons instead of jumping at bucket edges;
  * one model to tune and retrain monthly in the backtest.
The cost is that rows from the same origin are correlated (they share features),
which matters for validation, not for trees: validation is always a later,
disjoint time block, never a random split.
"""

from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml

from carbon_forecast.config import ROOT
from carbon_forecast.dataset import LEAKY_PREFIXES, NEVER_FEATURES, TARGET

PARAMS_PATH = ROOT / "config" / "lgbm_params.yaml"

# Fixed settings: quiet, reproducible run-to-run.
BASE_PARAMS: dict[str, Any] = {
    "verbosity": -1,
    "deterministic": True,
    "force_row_wise": True,
    "metric": "l1",
}


class LGBMForecaster:
    def __init__(
        self,
        features: list[str],
        params: dict[str, Any],
        num_boost_round: int,
        seed: int = 42,
        allow_leaky: bool = False,
    ):
        bad = [f for f in features if f.startswith(NEVER_FEATURES)]
        leaky = [f for f in features if f.startswith(LEAKY_PREFIXES)]
        if bad:
            raise ValueError(f"not allowed as features: {bad}")
        if leaky and not allow_leaky:
            raise ValueError(f"leaky features {leaky} need allow_leaky=True")
        self.features = list(features)
        self.params = {**BASE_PARAMS, **params, "seed": seed}
        self.num_boost_round = num_boost_round
        self.booster: lgb.Booster | None = None
        self.best_iteration: int | None = None

    def fit(
        self,
        train: pd.DataFrame,
        valid: pd.DataFrame | None = None,
        early_stopping_rounds: int | None = None,
    ) -> "LGBMForecaster":
        dtrain = lgb.Dataset(train[self.features], label=train[TARGET], free_raw_data=True)
        valid_sets, callbacks = [], []
        if valid is not None:
            valid_sets = [lgb.Dataset(valid[self.features], label=valid[TARGET], reference=dtrain)]
            if early_stopping_rounds:
                callbacks.append(lgb.early_stopping(early_stopping_rounds, verbose=False))
        self.booster = lgb.train(
            self.params,
            dtrain,
            num_boost_round=self.num_boost_round,
            valid_sets=valid_sets,
            callbacks=callbacks,
        )
        self.best_iteration = self.booster.best_iteration or self.num_boost_round
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        if self.booster is None:
            raise RuntimeError("fit() first")
        return self.booster.predict(df[self.features], num_iteration=self.best_iteration)

    def feature_importance(self, kind: str = "gain") -> pd.Series:
        imp = self.booster.feature_importance(importance_type=kind, iteration=self.best_iteration)
        return pd.Series(imp, index=self.features).sort_values(ascending=False)


def quantile_params(params: dict[str, Any], alpha: float) -> dict[str, Any]:
    """Same model settings, trained for the `alpha` quantile instead of the mean."""
    return {**params, "objective": "quantile", "alpha": alpha, "metric": "quantile"}


def load_tuned(path: Path = PARAMS_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `python -m carbon_forecast.models.tune`")
    return yaml.safe_load(path.read_text())


def variant_spec(variant: str, settings: dict, tuned: dict[str, Any]) -> dict[str, Any]:
    """Prefixes, training start, params and rounds for a named model variant."""
    cfg = settings["model"]["variants"][variant]
    source = cfg.get("params_from", variant)
    return {
        "prefixes": list(cfg["prefixes"]),
        "train_start": cfg["train_start"],
        "leaky": bool(cfg.get("leaky", False)),
        "params": tuned[source]["params"],
        "num_boost_round": tuned[source]["num_boost_round"],
    }
