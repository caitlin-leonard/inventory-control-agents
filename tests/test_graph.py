import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from inventory_agents import db
from inventory_agents.graph import run_event
from inventory_agents.schemas import EventType, InventoryEvent, SKU


@pytest.fixture
def seeded_db():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "t.db"
        db.init_db(p)
        with db.connect(p) as c:
            c.execute("INSERT INTO skus VALUES ('A','a','c',5.0,7,100,75,0.25)")
            c.execute("INSERT INTO inventory VALUES ('A',10,0)")
            for day in range(120):
                c.execute("INSERT INTO sales_history VALUES ('A',?,?)", (day, 30.0))
        yield p


def test_graph_runs_end_to_end(seeded_db):
    state = run_event(InventoryEvent(event_type=EventType.LOW_STOCK_ALERT, sku_ids=["A"]),
                      db_path=seeded_db)
    assert "decision" in state
    assert state["decision"].triage_route == "analyze"
    # low stock + steady demand => should propose an order
    po = state["decision"].purchase_orders[0]
    assert po.qty > 0


def test_trace_records_all_nodes(seeded_db):
    state = run_event(InventoryEvent(event_type=EventType.CYCLE_REVIEW), db_path=seeded_db)
    nodes = [t["node"] for t in state["trace"]]
    assert nodes == ["triage", "stock_analysis", "purchase"]


def test_supplier_delay_routes_to_expedite_but_still_plans(seeded_db):
    state = run_event(InventoryEvent(event_type=EventType.SUPPLIER_DELAY, sku_ids=["A"]),
                      db_path=seeded_db)
    assert state["triage"].route == "expedite"
    assert len(state["decision"].reorder_plans) == 1
