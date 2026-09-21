import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inventory_agents.forecasting import forecast_demand


def test_smooth_series_uses_smoothing_not_croston():
    fo = forecast_demand([40] * 60, horizon_days=30)
    assert fo.method in ("simple_exp_smoothing", "holt_linear")
    assert 35 < fo.mean_daily < 45
    assert abs(fo.forecast_units - fo.mean_daily * 30) < 1e-6


def test_intermittent_series_uses_croston():
    series = [0, 0, 0, 10, 0, 0, 0, 12, 0, 0, 0, 8] * 5
    fo = forecast_demand(series, horizon_days=30)
    assert fo.method == "crostons"
    assert fo.mean_daily > 0


def test_trending_series_detected():
    series = [float(i) for i in range(1, 61)]  # strong upward trend
    fo = forecast_demand(series, horizon_days=30)
    assert fo.method == "holt_linear"
    assert fo.mean_daily > series[-1]  # projects the trend forward


def test_empty_series_is_safe():
    fo = forecast_demand([], horizon_days=30)
    assert fo.mean_daily == 0 and fo.forecast_units == 0
