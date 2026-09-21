"""Purchase agent: turn reorder plans into guardrailed purchase orders.

Flow per SKU below reorder point:
  1. LLM proposes a quantity (PurchaseProposal) — bounded by the plan.
  2. The GuardrailEngine validates/clamps/blocks it against live budget,
     capacity, per-SKU value, per-order cap, MOQ and duplicate-PO rules.
  3. Approved/clamped POs are persisted and decrement the running budget +
     warehouse headroom so later SKUs in the same batch see the true remaining
     resources (this is what prevents the batch as a whole from over-committing).
"""
from __future__ import annotations

from .. import db
from ..config import POLICY
from ..guardrails import GuardrailContext, GuardrailEngine
from ..llm import LLMClient
from ..schemas import (
    Decision, GraphState, PurchaseOrder, PurchaseProposal, ReorderPlan,
)


def purchase_node(state: GraphState, llm: LLMClient, db_path=db.DEFAULT_DB) -> GraphState:
    skus = db.get_skus(db_path)
    inventory = db.get_inventory(db_path)
    plans: list[ReorderPlan] = state.get("reorder_plans", [])

    # Build the shared guardrail context for the whole batch.
    warehouse_used = sum(s.on_hand + s.on_order for s in inventory.values())
    ctx = GuardrailContext(
        policy=POLICY,
        remaining_budget=POLICY.purchase_budget_per_cycle,
        open_po_skus=db.open_po_skus(db_path),
        warehouse_used=warehouse_used,
    )
    engine = GuardrailEngine(ctx)

    proposals: list[PurchaseProposal] = []
    orders: list[PurchaseOrder] = []
    total_spend = 0.0
    rejected = 0

    # Prioritize the most at-risk SKUs first (deepest below ROP) so scarce budget
    # protects the highest stockout risk.
    ranked = sorted(
        [p for p in plans if p.below_reorder_point],
        key=lambda p: (p.reorder_point - p.position), reverse=True,
    )

    for plan in ranked:
        sku = skus[plan.sku_id]
        snap = inventory[plan.sku_id]
        proposal = llm.structured(
            PurchaseProposal,
            "You are the purchasing agent. Propose an order quantity to restore cover. "
            "Never exceed the recommended plan quantity.",
            f"SKU {plan.sku_id}: position {plan.position}, ROP {plan.reorder_point:.0f}, "
            f"recommended {plan.recommended_qty}.",
            plan=plan,
        )
        proposals.append(proposal)

        final_qty, status, results = engine.evaluate(sku, proposal, snap)
        order_value = final_qty * sku.unit_cost
        po = PurchaseOrder(
            sku_id=plan.sku_id, qty=final_qty, unit_cost=sku.unit_cost,
            supplier_lead_time_days=sku.lead_time_days, status=status,
            order_value=round(order_value, 2), guardrails=results,
            rationale=proposal.reasoning,
        )
        orders.append(po)

        if status == "rejected" or final_qty == 0:
            rejected += 1
            continue

        # Commit resources so subsequent SKUs see the truth.
        ctx.remaining_budget -= order_value
        ctx.warehouse_used += final_qty
        ctx.open_po_skus.add(plan.sku_id)
        total_spend += order_value
        db.record_po(po.model_dump(include={"sku_id", "qty", "unit_cost", "status", "order_value"}), db_path)

    decision = Decision(
        event=state["event"],
        triage_route=state["triage"].route if state.get("triage") else "n/a",
        analyzed_skus=[p.sku_id for p in plans],
        reorder_plans=plans,
        purchase_orders=orders,
        total_committed_spend=round(total_spend, 2),
        rejected_count=rejected,
        notes=[f"{len(orders)} POs generated, {rejected} rejected/blocked, "
               f"${total_spend:,.0f} committed of ${POLICY.purchase_budget_per_cycle:,.0f} budget."],
    )
    db.log_audit("purchase", decision.model_dump(), db_path)

    return {
        "proposals": proposals,
        "purchase_orders": orders,
        "decision": decision,
        "trace": [{"node": "purchase", "orders": len(orders), "rejected": rejected,
                   "committed_spend": round(total_spend, 2)}],
    }
