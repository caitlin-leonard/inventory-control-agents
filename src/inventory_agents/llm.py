"""Pluggable LLM client with structured-output guarantees.

The whole system talks to `LLMClient.structured(...)`, which always returns a
validated Pydantic object of the requested type. Two backends ship:

- RuleBasedLLM  : deterministic, offline default. Encodes sensible policy so the
                  graph runs end-to-end with no API key (great for CI, evals,
                  and reproducible demos).
- OpenAIClient  : real LLM via langchain-openai, with schema-validation + retry
                  as an output guardrail (invalid JSON is repaired, not trusted).

Swapping backends is a config change (LLM_PROVIDER), not a code change — the
agents never import a concrete client.
"""
from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from .config import POLICY, Policy
from .schemas import (
    InventoryEvent, EventType, PurchaseProposal, ReorderPlan, TriageDecision,
)

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Interface. `structured` returns a validated instance of `schema`."""

    def structured(self, schema: Type[T], system: str, user: str, **ctx) -> T:  # pragma: no cover
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Deterministic backend (default)
# --------------------------------------------------------------------------- #
class RuleBasedLLM(LLMClient):
    """Deterministic stand-in that mirrors what a well-prompted LLM should decide.

    It reads structured context passed by the agents (never free text parsing),
    so its behavior is predictable and testable. This is what lets the flagship
    run and be evaluated without external dependencies.
    """

    def __init__(self, policy: Policy = POLICY):
        self.policy = policy

    def structured(self, schema: Type[T], system: str, user: str, **ctx) -> T:
        if schema is TriageDecision:
            return self._triage(ctx["event"])  # type: ignore[return-value]
        if schema is PurchaseProposal:
            return self._purchase(ctx["plan"])  # type: ignore[return-value]
        raise ValueError(f"RuleBasedLLM has no policy for schema {schema.__name__}")

    def _triage(self, event: InventoryEvent) -> TriageDecision:
        mapping = {
            EventType.LOW_STOCK_ALERT: ("analyze", "high", "Low-stock alert => run reorder analysis."),
            EventType.DEMAND_SPIKE:    ("analyze", "high", "Demand spike => re-forecast and analyze."),
            EventType.CYCLE_REVIEW:    ("analyze", "medium", "Periodic review => analyze all SKUs."),
            EventType.SUPPLIER_DELAY:  ("expedite", "high", "Supplier delay => expedite / find alternates."),
            EventType.MANUAL_QUERY:    ("analyze", "low", "Manual query => analyze requested SKUs."),
        }
        route, priority, reasoning = mapping[event.event_type]
        return TriageDecision(route=route, priority=priority, reasoning=reasoning)

    def _purchase(self, plan: ReorderPlan) -> PurchaseProposal:
        qty = plan.recommended_qty if plan.below_reorder_point else 0
        reason = (
            f"Position {plan.position} < ROP {plan.reorder_point:.0f}; order {qty} "
            f"(EOQ {plan.eoq}) to restore cover."
            if plan.below_reorder_point else
            f"Position {plan.position} >= ROP {plan.reorder_point:.0f}; no order."
        )
        return PurchaseProposal(sku_id=plan.sku_id, proposed_qty=qty, reasoning=reason)


# --------------------------------------------------------------------------- #
# Real LLM backend (used when LLM_PROVIDER=openai and a key is set)
# --------------------------------------------------------------------------- #
class OpenAIClient(LLMClient):
    """Real structured output with validation + repair retry (output guardrail)."""

    def __init__(self, policy: Policy = POLICY):
        self.policy = policy
        try:
            from langchain_openai import ChatOpenAI  # noqa
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "langchain-openai not installed. `pip install langchain-openai` "
                "and set OPENAI_API_KEY, or use LLM_PROVIDER=rule_based."
            ) from e
        from langchain_openai import ChatOpenAI
        self._model = ChatOpenAI(model=policy.llm_model, temperature=0)

    def structured(self, schema: Type[T], system: str, user: str, **ctx) -> T:
        model = self._model.with_structured_output(schema)
        last_err: Exception | None = None
        for attempt in range(self.policy.llm_max_retries + 1):
            try:
                obj = model.invoke([("system", system), ("user", user)])
                return schema.model_validate(obj if isinstance(obj, dict) else obj.model_dump())
            except (ValidationError, ValueError) as e:  # pragma: no cover - needs network
                last_err = e
                user = f"{user}\n\nYour previous output was invalid: {e}. Return valid JSON only."
        raise RuntimeError(f"LLM failed structured output after retries: {last_err}")


def build_llm(policy: Policy = POLICY) -> LLMClient:
    if policy.llm_provider == "openai":
        return OpenAIClient(policy)
    return RuleBasedLLM(policy)
