import math

import numpy as np
import pytest

from carbon_forecast.models.conformal import calibrate, conformal_quantile, conformity_scores


def test_conformity_scores_sign():
    y = np.array([5.0, 0.0, 12.0])
    s = conformity_scores(y, lo=np.full(3, 2.0), hi=np.full(3, 10.0))
    assert s.tolist() == [-3.0, 2.0, 2.0]  # inside -> negative distance to nearest edge


def test_conformal_quantile_index():
    scores = np.arange(1, 10, dtype=float)  # n = 9
    assert conformal_quantile(scores, 0.2) == 8.0  # ceil(10 * 0.8) = 8th smallest
    assert conformal_quantile(scores, 0.5) == 5.0
    assert math.isinf(conformal_quantile(scores, 0.05))  # needs the 10th of 9
    assert math.isinf(conformal_quantile(np.array([]), 0.2))


def test_cqr_fixes_undercovering_band_on_exchangeable_data():
    rng = np.random.default_rng(0)
    n_cal, n_test = 2000, 20000
    x = rng.uniform(0, 1, n_cal + n_test)
    y = 3 * x + rng.normal(0, 1 + x, n_cal + n_test)  # heteroscedastic noise
    # A deliberately too-narrow "quantile model": true 10/90% half-width is ~1.28 sigma.
    lo, hi = 3 * x - 0.6 * (1 + x), 3 * x + 0.6 * (1 + x)
    cal, test = slice(0, n_cal), slice(n_cal, None)
    raw = np.mean((y[test] >= lo[test]) & (y[test] <= hi[test]))
    q = calibrate(y[cal], lo[cal], hi[cal], alpha=0.2)
    fixed = np.mean((y[test] >= lo[test] - q) & (y[test] <= hi[test] + q))
    assert raw < 0.5
    assert q > 0
    assert fixed == pytest.approx(0.8, abs=0.02)


def test_cqr_narrows_an_overcovering_band():
    rng = np.random.default_rng(1)
    y = rng.normal(0, 1, 5000)
    lo, hi = np.full(5000, -3.0), np.full(5000, 3.0)
    q = calibrate(y[:2000], lo[:2000], hi[:2000], alpha=0.2)
    assert q < 0
    cov = np.mean((y[2000:] >= lo[2000:] - q) & (y[2000:] <= hi[2000:] + q))
    assert cov == pytest.approx(0.8, abs=0.03)
