"""Typed domain models and the LangGraph state.

Pydantic is used both as the domain schema and as the *structured-output
contract* for the LLM: agents must return objects that validate against these
models, which is the first line of the guardrail defense.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# --------------------------------------------------------------------------- #
# Domain models
# --------------------------------------------------------------------------- #
class SKU(BaseModel):
    sku_id: str
    name: str
    category: str
    unit_cost: float = Field(gt=0)
    lead_time_days: int = Field(ge=1)
    moq: int = Field(ge=0, description="Supplier minimum order quantity")
    order_cost: float = Field(ge=0, description="Fixed cost to place one order")
    holding_cost_rate: float = Field(gt=0, description="Annual holding cost as % of unit cost")


class InventorySnapshot(BaseModel):
    sku_id: str
    on_hand: int = Field(ge=0)
    on_order: int = Field(ge=0, description="Units already committed on open POs")


class DemandForecast(BaseModel):
    sku_id: str
    method: str
    mean_daily: float
    std_daily: float
    horizon_days: int
    forecast_units: float


class ReorderPlan(BaseModel):
    sku_id: str
    reorder_point: float
    safety_stock: float
    eoq: int
    position: int = Field(description="on_hand + on_order")
    below_reorder_point: bool
    recommended_qty: int = Field(ge=0)
    rationale: str = ""


class EventType(str, Enum):
    LOW_STOCK_ALERT = "low_stock_alert"
    DEMAND_SPIKE = "demand_spike"
    SUPPLIER_DELAY = "supplier_delay"
    CYCLE_REVIEW = "cycle_review"      # periodic full review
    MANUAL_QUERY = "manual_query"


class InventoryEvent(BaseModel):
    event_type: EventType
    sku_ids: list[str] = Field(default_factory=list, description="empty => all SKUs")
    note: str = ""


class GuardrailResult(BaseModel):
    rule: str
    passed: bool
    reason: str
    # If a rule clamped a quantity, the adjusted value is recorded for the audit trail.
    adjusted_qty: Optional[int] = None


class PurchaseOrder(BaseModel):
    sku_id: str
    qty: int = Field(ge=0)
    unit_cost: float
    supplier_lead_time_days: int
    status: Literal["approved", "rejected", "clamped"] = "approved"
    order_value: float = 0.0
    guardrails: list[GuardrailResult] = Field(default_factory=list)
    rationale: str = ""


class Decision(BaseModel):
    """The full, auditable output of one graph run."""
    event: InventoryEvent
    triage_route: str
    analyzed_skus: list[str] = Field(default_factory=list)
    reorder_plans: list[ReorderPlan] = Field(default_factory=list)
    purchase_orders: list[PurchaseOrder] = Field(default_factory=list)
    total_committed_spend: float = 0.0
    rejected_count: int = 0
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# LLM structured-output contracts (what each agent must emit)
# --------------------------------------------------------------------------- #
class TriageDecision(BaseModel):
    route: Literal["analyze", "expedite", "no_action"]
    priority: Literal["low", "medium", "high"]
    reasoning: str


class PurchaseProposal(BaseModel):
    """What the purchase agent proposes *before* guardrails run."""
    sku_id: str
    proposed_qty: int = Field(ge=0)
    reasoning: str


# --------------------------------------------------------------------------- #
# LangGraph state
# --------------------------------------------------------------------------- #
def _last(a, b):
    """Reducer: keep the most recent write."""
    return b if b is not None else a


class GraphState(TypedDict, total=False):
    event: InventoryEvent
    triage: TriageDecision
    reorder_plans: list[ReorderPlan]
    proposals: list[PurchaseProposal]
    purchase_orders: list[PurchaseOrder]
    decision: Decision
    # audit metadata accumulated across nodes
    trace: Annotated[list[dict], lambda a, b: (a or []) + (b or [])]
