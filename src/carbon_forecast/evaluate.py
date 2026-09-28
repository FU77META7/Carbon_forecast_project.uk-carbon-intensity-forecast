"""Forecast accuracy metrics."""

import numpy as np
import pandas as pd


def mae(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs(p - y)))


def rmse(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.sqrt(np.mean((p - y) ** 2)))


def mape(y: np.ndarray, p: np.ndarray) -> float:
    """Mean absolute percentage error in %, over rows with a non-zero actual."""
    nz = y != 0
    return float(np.mean(np.abs((p[nz] - y[nz]) / y[nz])) * 100)


def skill(model_mae: float, reference_mae: float) -> float:
    """1 - MAE_model / MAE_reference: > 0 means better than the reference."""
    return 1.0 - model_mae / reference_mae


def score(y, p) -> dict[str, float]:
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    ok = ~(np.isnan(y) | np.isnan(p))
    y, p = y[ok], p[ok]
    return {"n": int(ok.sum()), "mae": mae(y, p), "rmse": rmse(y, p), "mape": mape(y, p)}


def score_table(df: pd.DataFrame, target: str, prediction_cols: list[str]) -> pd.DataFrame:
    """Metrics for several prediction columns, on rows where ALL of them exist,
    so every model is scored on exactly the same targets."""
    common = df.dropna(subset=[target, *prediction_cols])
    rows = {c: score(common[target], common[c]) for c in prediction_cols}
    return pd.DataFrame(rows).T
