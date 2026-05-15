"""
No-arbitrage diagnostics — Durrleman, Lee wing, calendar.

These are checks, not fits. The SSVI calibrator hard-enforces the
Gatheral-Jacquier butterfly bound during fitting (so SSVI g(k) is
non-negative by construction); the SABR fit has no such guarantee, and
we surface the diagnostic so the UI can flag violations.

The Durrleman g function is the same quantity that appears in the
Gatheral closed-form RND — see ``rnd.rnd_gatheral_one``.
"""

from __future__ import annotations

import numpy as np


def durrleman_g(
    k: np.ndarray,
    w: np.ndarray,
    w_prime: np.ndarray,
    w_double: np.ndarray,
) -> np.ndarray:
    """Durrleman butterfly indicator ``g(k)``.

    g(k) = (1 − k·w'/(2·w))² − w'²/4·(1/w + 1/4) + w''/2.

    g(k) ≥ 0 for all k is necessary-and-sufficient for the slice to be
    butterfly-arb-free (Gatheral 2014).
    """
    safe_w = np.maximum(w, 1e-12)
    term_1 = (1.0 - k * w_prime / (2.0 * safe_w)) ** 2
    term_2 = (w_prime * w_prime) / 4.0 * (1.0 / safe_w + 0.25)
    return term_1 - term_2 + w_double / 2.0


def lee_wing_slopes(
    K_grid: np.ndarray, iv_grid: np.ndarray, T: float, F: float
) -> tuple[float, float]:
    """Empirical wing slopes ``b_± = lim_{k → ±∞} w(k)/|k|`` from the
    fitted IV curve.

    Lee 2004 bound: ``b_± ≤ 2``. Slopes are estimated by linear regression
    of ``w(k) = σ²(k)·T`` against ``|k|`` over the last 20 % of the grid
    on each side. Returns ``(b_left, b_right)``.
    """
    k = np.log(np.asarray(K_grid, dtype=float) / F)
    w = np.asarray(iv_grid, dtype=float) ** 2 * T
    n = len(k)
    wing = max(int(n * 0.2), 3)

    # Right wing: k > 0, fit w = b·k + c using the rightmost ``wing`` points.
    right_idx = slice(n - wing, n)
    k_r = k[right_idx]
    w_r = w[right_idx]
    if np.any(k_r > 0):
        A = np.column_stack([k_r, np.ones_like(k_r)])
        slope_r, _ = np.linalg.lstsq(A, w_r, rcond=None)[0]
        b_right = float(slope_r)
    else:
        b_right = float("nan")

    # Left wing: k < 0, fit w = b·|k| + c using the leftmost ``wing`` points.
    left_idx = slice(0, wing)
    k_l = k[left_idx]
    w_l = w[left_idx]
    if np.any(k_l < 0):
        A = np.column_stack([-k_l, np.ones_like(k_l)])
        slope_l, _ = np.linalg.lstsq(A, w_l, rcond=None)[0]
        b_left = float(slope_l)
    else:
        b_left = float("nan")

    return b_left, b_right


def calendar_violation(
    slices: list[tuple[float, np.ndarray, np.ndarray]],
    F_values: list[float],
) -> dict[str, float | int]:
    """Detect calendar-arbitrage between expiry slices.

    No-arb condition: for any fixed ``k = log(K/F_T)``, total variance
    ``w(k, T) = σ²(k, T)·T`` is non-decreasing in T. Crossings of the
    total-variance curves between adjacent expiries indicate arbitrage.

    Args:
        slices: list of ``(T, K_grid, iv_grid)`` triples, ordered by T.
        F_values: forwards per slice, aligned with ``slices``.

    Returns:
        Dict with ``n_violations`` (count of (k, T) cells where
        ``w(k, T_{i+1}) < w(k, T_i)``) and ``worst_violation`` (largest
        absolute drop in pp²).
    """
    if len(slices) < 2:
        return {"n_violations": 0, "worst_violation": 0.0}

    # Common log-moneyness grid in the intersection of all slices.
    all_k_lo = []
    all_k_hi = []
    for (_, K_grid, _), F in zip(slices, F_values, strict=True):
        k_slice = np.log(np.asarray(K_grid, dtype=float) / F)
        all_k_lo.append(float(np.min(k_slice)))
        all_k_hi.append(float(np.max(k_slice)))
    k_lo = max(all_k_lo)
    k_hi = min(all_k_hi)
    if k_hi <= k_lo:
        return {"n_violations": 0, "worst_violation": 0.0}
    k_common = np.linspace(k_lo, k_hi, 50)

    # Interpolate total variance for each slice onto the common k grid.
    w_grids: list[np.ndarray] = []
    for (T_s, K_grid, iv_grid), F in zip(slices, F_values, strict=True):
        k_slice = np.log(np.asarray(K_grid, dtype=float) / F)
        w_slice = np.asarray(iv_grid, dtype=float) ** 2 * T_s
        w_grids.append(np.interp(k_common, k_slice, w_slice))

    n_violations = 0
    worst = 0.0
    for i in range(len(w_grids) - 1):
        diff = w_grids[i + 1] - w_grids[i]
        bad = diff < 0
        n_violations += int(bad.sum())
        if bad.any():
            worst = max(worst, float(-np.min(diff[bad])))

    return {"n_violations": int(n_violations), "worst_violation": float(worst)}
