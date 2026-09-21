"""Command-line runner: fire an event through the multi-agent graph and print
the decision + audit trail.

Examples:
  python -m inventory_agents.cli cycle_review
  python -m inventory_agents.cli low_stock_alert SKU-1001 SKU-1003
"""
from __future__ import annotations

import sys

from . import db
from .graph import run_event
from .schemas import EventType, InventoryEvent


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print(__doc__)
        return
    event_type = EventType(argv[0])
    sku_ids = argv[1:]
    db.init_db()
    state = run_event(InventoryEvent(event_type=event_type, sku_ids=sku_ids))
    decision = state["decision"]

    print(f"\n=== Event: {event_type.value}  |  route: {decision.triage_route} ===")
    print(f"Analyzed {len(decision.analyzed_skus)} SKUs; "
          f"{sum(p.below_reorder_point for p in decision.reorder_plans)} below reorder point.\n")
    for po in decision.purchase_orders:
        flag = {"approved": "OK ", "clamped": "CLMP", "rejected": "REJ "}[po.status]
        print(f"  [{flag}] {po.sku_id}: qty={po.qty:>5}  ${po.order_value:>10,.0f}  {po.rationale}")
        for g in po.guardrails:
            if not g.passed:
                print(f"         ! {g.rule}: {g.reason}")
    print(f"\nCommitted ${decision.total_committed_spend:,.0f} / "
          f"budget; {decision.rejected_count} rejected/blocked.")
    print("Trace:", " -> ".join(t["node"] for t in state.get("trace", [])))


if __name__ == "__main__":
    main()
