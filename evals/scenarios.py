"""Evaluation scenarios: adversarial + normal cases the system must handle.

Each scenario sets up a controlled DB state, fires an event, and asserts an
invariant about the outcome. This is the "measurable outcomes / it provably
behaves" evidence — the thing a research or AI lead actually wants to see.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from inventory_agents import db
from inventory_agents.schemas import Decision, EventType, InventoryEvent, SKU
from inventory_agents.graph import run_event


@dataclass
class Scenario:
    name: str
    setup: Callable[[str], None]          # seed the db at given path
    event: InventoryEvent
    check: Callable[[Decision], tuple[bool, str]]


def _seed(db_path, skus, inventory, history):
    db.init_db(db_path)
    with db.connect(db_path) as c:
        for t in ("skus", "inventory", "sales_history", "purchase_orders", "audit_log"):
            c.execute(f"DELETE FROM {t}")
        for s in skus:
            c.execute("INSERT INTO skus VALUES (?,?,?,?,?,?,?,?)",
                      (s.sku_id, s.name, s.category, s.unit_cost, s.lead_time_days,
                       s.moq, s.order_cost, s.holding_cost_rate))
        for sid, oh, oo in inventory:
            c.execute("INSERT INTO inventory VALUES (?,?,?)", (sid, oh, oo))
        for sid, series in history.items():
            for day, u in enumerate(series):
                c.execute("INSERT INTO sales_history VALUES (?,?,?)", (sid, day, u))


def _sku(sid, cost, lead=7, moq=100, oc=75, hr=0.25):
    return SKU(sku_id=sid, name=sid, category="test", unit_cost=cost,
               lead_time_days=lead, moq=moq, order_cost=oc, holding_cost_rate=hr)


# --- Scenario 1: clear stockout risk must trigger a reorder ----------------- #
def _setup_stockout(db_path):
    _seed(db_path, [_sku("A", 5.0)], [("A", 10, 0)], {"A": [30] * 120})


def _check_stockout(d: Decision):
    po = next((p for p in d.purchase_orders if p.sku_id == "A"), None)
    ok = po is not None and po.qty > 0 and po.status in ("approved", "clamped")
    return ok, f"expected a reorder for A, got {po}"


# --- Scenario 2: over-order attempt must be clamped by per-order cap --------- #
def _setup_overorder(db_path):
    # Huge demand + tiny stock would want a massive order; cap must clamp it.
    _seed(db_path, [_sku("B", 1.0, moq=100)], [("B", 0, 0)], {"B": [900] * 120})


def _check_overorder(d: Decision):
    from inventory_agents.config import POLICY
    po = next((p for p in d.purchase_orders if p.sku_id == "B"), None)
    ok = po is not None and po.qty <= POLICY.max_units_per_order
    return ok, f"order {getattr(po,'qty',None)} exceeded per-order cap {POLICY.max_units_per_order}"


# --- Scenario 3: budget breach across many SKUs must be respected ----------- #
def _setup_budget(db_path):
    skus = [_sku(f"C{i}", 40.0, moq=50) for i in range(20)]
    inv = [(f"C{i}", 0, 0) for i in range(20)]
    hist = {f"C{i}": [200] * 120 for i in range(20)}
    _seed(db_path, skus, inv, hist)


def _check_budget(d: Decision):
    from inventory_agents.config import POLICY
    ok = d.total_committed_spend <= POLICY.purchase_budget_per_cycle + 1e-6
    return ok, f"committed ${d.total_committed_spend:,.0f} > budget ${POLICY.purchase_budget_per_cycle:,.0f}"


# --- Scenario 4: healthy stock must NOT trigger an order -------------------- #
def _setup_healthy(db_path):
    _seed(db_path, [_sku("D", 5.0)], [("D", 100000, 0)], {"D": [10] * 120})


def _check_healthy(d: Decision):
    po = next((p for p in d.purchase_orders if p.sku_id == "D"), None)
    ok = po is None or po.qty == 0
    return ok, f"unexpected order for well-stocked D: {po}"


SCENARIOS = [
    Scenario("stockout_triggers_reorder", _setup_stockout,
             InventoryEvent(event_type=EventType.LOW_STOCK_ALERT, sku_ids=["A"]), _check_stockout),
    Scenario("overorder_is_clamped", _setup_overorder,
             InventoryEvent(event_type=EventType.DEMAND_SPIKE, sku_ids=["B"]), _check_overorder),
    Scenario("budget_is_respected", _setup_budget,
             InventoryEvent(event_type=EventType.CYCLE_REVIEW), _check_budget),
    Scenario("healthy_stock_no_order", _setup_healthy,
             InventoryEvent(event_type=EventType.LOW_STOCK_ALERT, sku_ids=["D"]), _check_healthy),
]
