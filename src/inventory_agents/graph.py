r"""LangGraph assembly.

    START -> triage -> (conditional) -> stock_analysis -> purchase -> END
                    \-> END   (when route == no_action)

The graph is compiled once and can be invoked per event. Nodes are bound to a
concrete LLM client and DB path via closures so the graph itself stays pure.
"""
from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from . import db
from .agents import purchase_node, stock_analysis_node, triage_node
from .llm import LLMClient, build_llm
from .schemas import GraphState, InventoryEvent


def _route_after_triage(state: GraphState) -> str:
    route = state["triage"].route
    return "analyze" if route in ("analyze", "expedite") else "end"


def build_graph(llm: LLMClient | None = None, db_path=db.DEFAULT_DB):
    llm = llm or build_llm()
    g = StateGraph(GraphState)

    g.add_node("triage", partial(triage_node, llm=llm))
    g.add_node("stock_analysis", partial(stock_analysis_node, db_path=db_path))
    g.add_node("purchase", partial(purchase_node, llm=llm, db_path=db_path))

    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", _route_after_triage,
                            {"analyze": "stock_analysis", "end": END})
    g.add_edge("stock_analysis", "purchase")
    g.add_edge("purchase", END)
    return g.compile()


def run_event(event: InventoryEvent, llm: LLMClient | None = None, db_path=db.DEFAULT_DB) -> GraphState:
    graph = build_graph(llm=llm, db_path=db_path)
    return graph.invoke({"event": event})
