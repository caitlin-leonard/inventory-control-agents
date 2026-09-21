"""Stock-analysis agent: forecast demand and compute reorder plans.

This node is where the quantitative core lives. For each in-scope SKU it:
  1. pulls sales history,
  2. forecasts demand over the policy horizon,
  3. computes safety stock / reorder point / EOQ,
  4. produces a ReorderPlan flagging whether we're below the reorder point.

The LLM is intentionally NOT trusted with arithmetic — the numbers come from the
optimization module; the model's role elsewhere is routing and rationale.
"""
from __future__ import annotations

from .. import db
from ..config import POLICY
from ..forecasting import forecast_demand
from ..optimization import plan_reorder
from ..schemas import DemandForecast, GraphState, ReorderPlan


def _scope_skus(state: GraphState, skus: dict) -> list[str]:
    requested = state["event"].sku_ids
    is_expedite = state.get("triage") and state["triage"].route == "expedite"
    ids = requested or list(skus.keys())
    return ids, is_expedite


def stock_analysis_node(state: GraphState, db_path=db.DEFAULT_DB) -> GraphState:
    skus = db.get_skus(db_path)
    inventory = db.get_inventory(db_path)
    ids, is_expedite = _scope_skus(state, skus)

    plans: list[ReorderPlan] = []
    for sid in ids:
        sku = skus.get(sid)
        snap = inventory.get(sid)
        if not sku or not snap:
            continue

        history = db.get_sales_history(sid, db_path)
        fo = forecast_demand(history, POLICY.forecast_horizon_days)
        forecast = DemandForecast(
            sku_id=sid, method=fo.method, mean_daily=fo.mean_daily,
            std_daily=fo.std_daily, horizon_days=fo.horizon_days,
            forecast_units=fo.forecast_units,
        )

        # Expedite path: supplier delay means we should plan as if lead time is
        # longer (more safety stock) — model the risk by inflating lead time 50%.
        effective_sku = sku
        if is_expedite:
            effective_sku = sku.model_copy(update={"lead_time_days": int(sku.lead_time_days * 1.5)})

        position = snap.on_hand + snap.on_order
        opt = plan_reorder(effective_sku, forecast, position, POLICY.default_service_level)

        plans.append(ReorderPlan(
            sku_id=sid,
            reorder_point=opt.reorder_point,
            safety_stock=opt.safety_stock,
            eoq=opt.eoq,
            position=position,
            below_reorder_point=opt.below_reorder_point,
            recommended_qty=opt.recommended_qty,
            rationale=(f"forecast[{fo.method}] mean/day={fo.mean_daily:.2f} "
                       f"sigma/day={fo.std_daily:.2f}; ROP={opt.reorder_point:.0f} "
                       f"SS={opt.safety_stock:.0f} EOQ={opt.eoq}"),
        ))

    return {
        "reorder_plans": plans,
        "trace": [{"node": "stock_analysis", "analyzed": len(plans),
                   "below_rop": sum(p.below_reorder_point for p in plans)}],
    }
