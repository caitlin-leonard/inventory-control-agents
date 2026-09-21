import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inventory_agents.optimization import (
    economic_order_qty, reorder_point, safety_stock, service_level_z, plan_reorder,
)
from inventory_agents.schemas import SKU, DemandForecast


def test_service_level_z_matches_known_values():
    assert abs(service_level_z(0.95) - 1.645) < 0.01
    assert abs(service_level_z(0.50) - 0.0) < 1e-6


def test_eoq_textbook_value():
    # D=1000, S=10, H=2 -> EOQ = sqrt(2*1000*10/2)=100
    assert economic_order_qty(1000, 10, 2) == 100


def test_higher_service_level_raises_safety_stock():
    lo = safety_stock(std_daily=5, lead_time_days=9, service_level=0.90)
    hi = safety_stock(std_daily=5, lead_time_days=9, service_level=0.99)
    assert hi > lo > 0


def test_reorder_point_includes_lead_demand_and_ss():
    ss = safety_stock(5, 9, 0.95)
    rop = reorder_point(mean_daily=20, lead_time_days=9, ss=ss)
    assert rop > 20 * 9  # strictly above mean lead-time demand


def test_plan_reorder_orders_when_below_rop():
    sku = SKU(sku_id="X", name="x", category="c", unit_cost=5, lead_time_days=7,
              moq=100, order_cost=75, holding_cost_rate=0.25)
    fc = DemandForecast(sku_id="X", method="test", mean_daily=30, std_daily=8,
                        horizon_days=30, forecast_units=900)
    res = plan_reorder(sku, fc, inventory_position=10, service_level=0.95)
    assert res.below_reorder_point is True
    assert res.recommended_qty >= sku.moq


def test_plan_reorder_no_order_when_healthy():
    sku = SKU(sku_id="X", name="x", category="c", unit_cost=5, lead_time_days=7,
              moq=100, order_cost=75, holding_cost_rate=0.25)
    fc = DemandForecast(sku_id="X", method="test", mean_daily=10, std_daily=2,
                        horizon_days=30, forecast_units=300)
    res = plan_reorder(sku, fc, inventory_position=100000, service_level=0.95)
    assert res.below_reorder_point is False
    assert res.recommended_qty == 0
