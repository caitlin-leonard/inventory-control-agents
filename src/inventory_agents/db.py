"""SQLite persistence: SKU catalog, inventory, sales history, open POs, audit log.

Kept intentionally small and dependency-free (stdlib sqlite3) so the repo runs
with `python -m ...` and no external services.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .schemas import SKU, InventorySnapshot

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "inventory.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS skus (
    sku_id TEXT PRIMARY KEY, name TEXT, category TEXT, unit_cost REAL,
    lead_time_days INTEGER, moq INTEGER, order_cost REAL, holding_cost_rate REAL
);
CREATE TABLE IF NOT EXISTS inventory (
    sku_id TEXT PRIMARY KEY, on_hand INTEGER, on_order INTEGER,
    FOREIGN KEY(sku_id) REFERENCES skus(sku_id)
);
CREATE TABLE IF NOT EXISTS sales_history (
    sku_id TEXT, day INTEGER, units REAL,
    PRIMARY KEY (sku_id, day)
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, sku_id TEXT, qty INTEGER,
    unit_cost REAL, status TEXT, order_value REAL, created_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, node TEXT, payload TEXT
);
"""


@contextmanager
def connect(db_path: Path | str = DEFAULT_DB):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | str = DEFAULT_DB) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as c:
        c.executescript(SCHEMA)


def get_skus(db_path: Path | str = DEFAULT_DB) -> dict[str, SKU]:
    with connect(db_path) as c:
        rows = c.execute("SELECT * FROM skus").fetchall()
    return {r["sku_id"]: SKU(**dict(r)) for r in rows}


def get_inventory(db_path: Path | str = DEFAULT_DB) -> dict[str, InventorySnapshot]:
    with connect(db_path) as c:
        rows = c.execute("SELECT * FROM inventory").fetchall()
    return {r["sku_id"]: InventorySnapshot(**dict(r)) for r in rows}


def get_sales_history(sku_id: str, db_path: Path | str = DEFAULT_DB) -> list[float]:
    with connect(db_path) as c:
        rows = c.execute(
            "SELECT units FROM sales_history WHERE sku_id=? ORDER BY day", (sku_id,)
        ).fetchall()
    return [r["units"] for r in rows]


def open_po_skus(db_path: Path | str = DEFAULT_DB) -> set[str]:
    with connect(db_path) as c:
        rows = c.execute(
            "SELECT DISTINCT sku_id FROM purchase_orders WHERE status='approved'"
        ).fetchall()
    return {r["sku_id"] for r in rows}


def record_po(po: dict, db_path: Path | str = DEFAULT_DB) -> None:
    from datetime import datetime, timezone
    with connect(db_path) as c:
        c.execute(
            "INSERT INTO purchase_orders (sku_id, qty, unit_cost, status, order_value, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (po["sku_id"], po["qty"], po["unit_cost"], po["status"], po["order_value"],
             datetime.now(timezone.utc).isoformat()),
        )
        if po["status"] in ("approved", "clamped") and po["qty"] > 0:
            c.execute(
                "UPDATE inventory SET on_order = on_order + ? WHERE sku_id=?",
                (po["qty"], po["sku_id"]),
            )


def log_audit(node: str, payload: dict, db_path: Path | str = DEFAULT_DB) -> None:
    from datetime import datetime, timezone
    with connect(db_path) as c:
        c.execute(
            "INSERT INTO audit_log (ts, node, payload) VALUES (?,?,?)",
            (datetime.now(timezone.utc).isoformat(), node, json.dumps(payload, default=str)),
        )
