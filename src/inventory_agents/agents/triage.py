"""Triage agent: classify the incoming event and pick a route.

Route semantics (consumed by the graph's conditional edge):
- analyze   -> run stock-analysis then purchase
- expedite  -> handle supplier delay (analyze with shortened effective lead time)
- no_action -> end early
"""
from __future__ import annotations

from ..llm import LLMClient
from ..schemas import GraphState, TriageDecision

SYSTEM = (
    "You are the triage agent in an inventory-control system. Classify the event "
    "and choose a route: analyze, expedite, or no_action. Be conservative: when in "
    "doubt, analyze."
)


def triage_node(state: GraphState, llm: LLMClient) -> GraphState:
    event = state["event"]
    decision: TriageDecision = llm.structured(
        TriageDecision, SYSTEM,
        f"Event: {event.event_type.value}. SKUs: {event.sku_ids or 'ALL'}. Note: {event.note}",
        event=event,
    )
    return {
        "triage": decision,
        "trace": [{"node": "triage", "route": decision.route, "priority": decision.priority,
                   "reasoning": decision.reasoning}],
    }
