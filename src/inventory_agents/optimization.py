"""Inventory optimization: EOQ, safety stock, reorder point.

Classic operations-research formulas, implemented transparently:

- Safety stock       SS = z * sigma_LT  where sigma_LT = sigma_d * sqrt(L)
- Reorder point      ROP = mu_d * L + SS
- Economic order qty EOQ = sqrt(2 * D * S / H)

`z` is the service-level multiplier from the inverse normal CDF, so a 95%
target in-stock probability maps to z ≈ 1.645.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

from .schemas import SKU, DemandForecast


def service_level_z(service_level: float) -> float:
    """Inverse normal CDF -> safety factor. Clamped to a sane range."""
    service_level = min(max(service_level, 0.50), 0.9999)
    return NormalDist().inv_cdf(service_level)


def safety_stock(std_daily: float, lead_time_days: int, service_level: float) -> float:
    z = service_level_z(service_level)
    sigma_lead_time = std_daily * math.sqrt(lead_time_days)
    return z * sigma_lead_time


def reorder_point(mean_daily: float, lead_time_days: int, ss: float) -> float:
    return mean_daily * lead_time_days + ss


def economic_order_qty(annual_demand: float, order_cost: float, holding_cost_per_unit: float) -> int:
    if annual_demand <= 0 or order_cost <= 0 or holding_cost_per_unit <= 0:
        return 0
    eoq = math.sqrt((2 * annual_demand * order_cost) / holding_cost_per_unit)
    return int(round(eoq))


@dataclass
class OptimizationResult:
    safety_stock: float
    reorder_point: float
    eoq: int
    below_reorder_point: bool
    recommended_qty: int


def plan_reorder(
    sku: SKU,
    forecast: DemandForecast,
    inventory_position: int,
    service_level: float,
) -> OptimizationResult:
    """Combine forecast + SKU economics into a concrete reorder recommendation.

    recommended_qty raises the position back above the reorder point, ordering in
    EOQ-sized batches (respecting MOQ) so we neither under- nor massively
    over-order.
    """
    ss = safety_stock(forecast.std_daily, sku.lead_time_days, service_level)
    rop = reorder_point(forecast.mean_daily, sku.lead_time_days, ss)

    annual_demand = forecast.mean_daily * 365
    holding_cost_per_unit = sku.unit_cost * sku.holding_cost_rate
    eoq = economic_order_qty(annual_demand, sku.order_cost, holding_cost_per_unit)

    below = inventory_position < rop
    recommended_qty = 0
    if below:
        # Target level = ROP + one EOQ batch of headroom (order-up-to logic).
        target = rop + max(eoq, 1)
        gap = math.ceil(target - inventory_position)
        # Order in EOQ multiples so runs are efficient; never below MOQ.
        if eoq > 0:
            batches = max(1, math.ceil(gap / eoq))
            recommended_qty = batches * eoq
        else:
            recommended_qty = gap
        recommended_qty = max(recommended_qty, sku.moq)

    return OptimizationResult(
        safety_stock=round(ss, 2),
        reorder_point=round(rop, 2),
        eoq=eoq,
        below_reorder_point=below,
        recommended_qty=int(recommended_qty),
    )
