import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inventory_agents.config import Policy
from inventory_agents.guardrails import GuardrailContext, GuardrailEngine
from inventory_agents.schemas import InventorySnapshot, PurchaseProposal, SKU


def _sku(**kw):
    base = dict(sku_id="A", name="a", category="c", unit_cost=1.0, lead_time_days=7,
                moq=100, order_cost=75, holding_cost_rate=0.25)
    base.update(kw)
    return SKU(**base)


def _engine(**ctx):
    policy = ctx.pop("policy", Policy())
    base = dict(policy=policy, remaining_budget=1e9, open_po_skus=set(), warehouse_used=0)
    base.update(ctx)
    return GuardrailEngine(GuardrailContext(**base))


def test_max_units_clamps():
    eng = _engine(policy=Policy(max_units_per_order=500))
    qty, status, _ = eng.evaluate(_sku(), PurchaseProposal(sku_id="A", proposed_qty=5000, reasoning=""),
                                  InventorySnapshot(sku_id="A", on_hand=0, on_order=0))
    assert qty == 500 and status == "clamped"


def test_budget_blocks_when_no_money():
    eng = _engine(remaining_budget=0.0)
    qty, status, _ = eng.evaluate(_sku(), PurchaseProposal(sku_id="A", proposed_qty=200, reasoning=""),
                                  InventorySnapshot(sku_id="A", on_hand=0, on_order=0))
    assert qty == 0 and status == "rejected"


def test_capacity_clamps_to_headroom():
    eng = _engine(policy=Policy(warehouse_capacity_units=1000), warehouse_used=900)
    qty, status, _ = eng.evaluate(_sku(moq=1), PurchaseProposal(sku_id="A", proposed_qty=500, reasoning=""),
                                  InventorySnapshot(sku_id="A", on_hand=0, on_order=0))
    assert qty == 100 and status == "clamped"


def test_duplicate_po_rejected():
    eng = _engine(open_po_skus={"A"})
    qty, status, results = eng.evaluate(_sku(), PurchaseProposal(sku_id="A", proposed_qty=200, reasoning=""),
                                        InventorySnapshot(sku_id="A", on_hand=0, on_order=0))
    assert qty == 0 and status == "rejected"
    assert any(r.rule == "no_duplicate_open_po" and not r.passed for r in results)


def test_moq_raises_small_order():
    eng = _engine()
    qty, status, _ = eng.evaluate(_sku(moq=100), PurchaseProposal(sku_id="A", proposed_qty=10, reasoning=""),
                                  InventorySnapshot(sku_id="A", on_hand=0, on_order=0))
    assert qty == 100 and status == "clamped"


def test_clamp_below_moq_is_rejected():
    # per-order cap forces qty under MOQ -> cannot place compliant order
    eng = _engine(policy=Policy(max_units_per_order=50))
    qty, status, _ = eng.evaluate(_sku(moq=100), PurchaseProposal(sku_id="A", proposed_qty=5000, reasoning=""),
                                  InventorySnapshot(sku_id="A", on_hand=0, on_order=0))
    assert qty == 0 and status == "rejected"
