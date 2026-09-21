"""Demand forecasting.

Deliberately dependency-light (pure Python + statistics) so the analytics are
transparent and testable. Three methods are provided; the engine picks based on
the demand signature (intermittent vs. smooth/trending).

References:
- Simple / double exponential smoothing (Holt) — standard time-series baselines.
- Croston's method — the classic estimator for intermittent demand.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass
class ForecastOutput:
    method: str
    mean_daily: float
    std_daily: float
    horizon_days: int
    forecast_units: float


def _moving_average(history: list[float], window: int = 14) -> float:
    if not history:
        return 0.0
    w = history[-window:]
    return sum(w) / len(w)


def _simple_exp_smoothing(history: list[float], alpha: float = 0.3) -> float:
    if not history:
        return 0.0
    level = history[0]
    for x in history[1:]:
        level = alpha * x + (1 - alpha) * level
    return level


def _holt_linear(history: list[float], alpha: float = 0.3, beta: float = 0.1) -> tuple[float, float]:
    """Double exponential smoothing. Returns (level, trend)."""
    if len(history) < 2:
        return (history[-1] if history else 0.0), 0.0
    level = history[0]
    trend = history[1] - history[0]
    for x in history[1:]:
        prev_level = level
        level = alpha * x + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
    return level, trend


def _crostons(history: list[float], alpha: float = 0.1) -> float:
    """Croston's method for intermittent demand -> average demand per period."""
    demands = [(i, v) for i, v in enumerate(history) if v > 0]
    if not demands:
        return 0.0
    z = demands[0][1]          # smoothed non-zero demand size
    x = 1.0                    # smoothed inter-arrival interval
    last_idx = demands[0][0]
    for idx, v in demands[1:]:
        gap = idx - last_idx
        z = alpha * v + (1 - alpha) * z
        x = alpha * gap + (1 - alpha) * x
        last_idx = idx
    return z / x if x > 0 else 0.0


def _intermittency(history: list[float]) -> float:
    if not history:
        return 1.0
    zeros = sum(1 for v in history if v <= 0)
    return zeros / len(history)


def forecast_demand(history: list[float], horizon_days: int) -> ForecastOutput:
    """Choose a method from the demand signature and forecast `horizon_days` ahead.

    - High intermittency (>40% zero-demand days) -> Croston's.
    - Otherwise -> Holt if a meaningful trend exists, else simple exp smoothing.
    """
    history = [max(0.0, float(x)) for x in history]
    if not history:
        return ForecastOutput("none", 0.0, 0.0, horizon_days, 0.0)

    std_daily = statistics.pstdev(history) if len(history) > 1 else 0.0
    intermittency = _intermittency(history)

    if intermittency > 0.40:
        mean_daily = _crostons(history)
        method = "crostons"
    else:
        level, trend = _holt_linear(history)
        # Use trend only if it is non-trivial relative to the level.
        if abs(trend) > 0.005 * max(level, 1e-9):
            mean_daily = max(0.0, level + trend * (horizon_days / 2))
            method = "holt_linear"
        else:
            mean_daily = max(0.0, _simple_exp_smoothing(history))
            method = "simple_exp_smoothing"

    forecast_units = mean_daily * horizon_days
    return ForecastOutput(method, mean_daily, std_daily, horizon_days, forecast_units)
