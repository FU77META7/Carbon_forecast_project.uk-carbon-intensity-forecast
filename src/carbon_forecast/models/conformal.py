"""Conformalized quantile regression (Romano, Patterson & Candes, 2019).

Quantile models give a band [lo, hi]. On a held-out calibration set, each row's
conformity score is how far the actual falls outside the band (negative when
inside): s = max(lo - y, y - hi). Widening both sides by the
ceil((n + 1)(1 - alpha))-th smallest score gives >= 1 - alpha coverage when
calibration and test rows are exchangeable. Time series are not exchangeable,
so for us the guarantee is approximate and coverage is measured, not assumed.
"""

import math

import numpy as np


def conformity_scores(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    return np.maximum(lo - y, y - hi)


def conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    """Finite-sample-corrected (1 - alpha) quantile of the conformity scores."""
    scores = np.sort(np.asarray(scores, dtype=float))
    n = len(scores)
    k = math.ceil((n + 1) * (1 - alpha))
    if n == 0 or k > n:
        return math.inf
    return float(scores[k - 1])


def calibrate(y_cal: np.ndarray, lo_cal: np.ndarray, hi_cal: np.ndarray, alpha: float) -> float:
    """Symmetric adjustment q: the calibrated band is [lo - q, hi + q]."""
    lo, hi = np.minimum(lo_cal, hi_cal), np.maximum(lo_cal, hi_cal)
    return conformal_quantile(conformity_scores(y_cal, lo, hi), alpha)
