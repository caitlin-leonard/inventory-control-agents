"""FastAPI surface exposing the agent system as a service.

Endpoints:
  GET  /health
  GET  /inventory            -> current stock positions
  GET  /skus                 -> catalog
  POST /events               -> run an event through the graph, return the Decision
  GET  /audit                -> recent audit-log entries

Run:  uvicorn inventory_agents.api:app --reload
"""
from __future__ import annotations

import json

from fastapi import FastAPI

from . import db
from .graph import run_event
from .schemas import Decision, InventoryEvent

app = FastAPI(title="Inventory Control Agents", version="0.1.0")


@app.on_event("startup")
def _startup():
    db.init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/skus")
def skus():
    return {k: v.model_dump() for k, v in db.get_skus().items()}


@app.get("/inventory")
def inventory():
    return {k: v.model_dump() for k, v in db.get_inventory().items()}


@app.post("/events", response_model=Decision)
def post_event(event: InventoryEvent):
    state = run_event(event)
    return state["decision"]


@app.get("/audit")
def audit(limit: int = 20):
    with db.connect() as c:
        rows = c.execute(
            "SELECT ts, node, payload FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"ts": r["ts"], "node": r["node"], "payload": json.loads(r["payload"])} for r in rows]
