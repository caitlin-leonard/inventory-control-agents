"""The guardrail engine.

Every purchase the LLM/agents propose passes through this layer before it can
become an approved PO. Rules are pure functions returning a GuardrailResult, so
they are independently unit-testable and fully auditable. The engine supports
two failure modes:

- CLAMP: the order is reduced to a safe value (e.g. exceeds max-units-per-order).
- BLOCK: the order is rejected outright (e.g. would breach budget or capacity).

This is the "agent can never over-order" property, enforced deterministically
rather than trusted to the model.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import Policy
from .schemas import GuardrailResult, PurchaseProposal, SKU, InventorySnapshot


@dataclass
class GuardrailContext:
    """Running state the engine needs to reason about the *whole* batch."""
    policy: Policy
    remaining_budget: float
    open_po_skus: set[str]           # SKUs that already have an open PO
    warehouse_used: int              # units currently on_hand + on_order across all SKUs


class GuardrailEngine:
    def __init__(self, context: GuardrailContext):
        self.ctx = context

    # --- Individual rules -------------------------------------------------- #
    def _rule_duplicate_po(self, sku: SKU) -> GuardrailResult:
        dup = sku.sku_id in self.ctx.open_po_skus
        return GuardrailResult(
            rule="no_duplicate_open_po", passed=not dup,
            reason="open PO already exists for this SKU" if dup else "no existing open PO",
        )

    def _rule_max_units(self, qty: int) -> GuardrailResult:
        cap = self.ctx.policy.max_units_per_order
        if qty <= cap:
            return GuardrailResult(rule="max_units_per_order", passed=True, reason=f"{qty} <= {cap}")
        return GuardrailResult(
            rule="max_units_per_order", passed=False,
            reason=f"requested {qty} exceeds per-order cap {cap}; clamped", adjusted_qty=cap,
        )

    def _rule_moq(self, sku: SKU, qty: int) -> GuardrailResult:
        if qty >= sku.moq:
            return GuardrailResult(rule="min_order_qty", passed=True, reason=f"{qty} >= MOQ {sku.moq}")
        return GuardrailResult(
            rule="min_order_qty", passed=False,
            reason=f"requested {qty} below MOQ {sku.moq}; raised", adjusted_qty=sku.moq,
        )

    def _rule_max_order_value(self, sku: SKU, qty: int) -> GuardrailResult:
        value = qty * sku.unit_cost
        cap = self.ctx.policy.max_order_value_per_sku
        if value <= cap:
            return GuardrailResult(rule="max_order_value_per_sku", passed=True, reason=f"${value:,.0f} <= ${cap:,.0f}")
        safe_qty = int(cap // sku.unit_cost)
        return GuardrailResult(
            rule="max_order_value_per_sku", passed=False,
            reason=f"${value:,.0f} exceeds per-SKU value cap ${cap:,.0f}; clamped", adjusted_qty=safe_qty,
        )

    def _rule_budget(self, sku: SKU, qty: int) -> GuardrailResult:
        value = qty * sku.unit_cost
        if value <= self.ctx.remaining_budget:
            return GuardrailResult(rule="budget_cap", passed=True, reason=f"${value:,.0f} within remaining ${self.ctx.remaining_budget:,.0f}")
        safe_qty = int(self.ctx.remaining_budget // sku.unit_cost)
        if safe_qty <= 0:
            return GuardrailResult(rule="budget_cap", passed=False, reason="no remaining budget; blocked", adjusted_qty=0)
        return GuardrailResult(
            rule="budget_cap", passed=False,
            reason=f"${value:,.0f} exceeds remaining budget ${self.ctx.remaining_budget:,.0f}; clamped", adjusted_qty=safe_qty,
        )

    def _rule_capacity(self, qty: int) -> GuardrailResult:
        cap = self.ctx.policy.warehouse_capacity_units
        projected = self.ctx.warehouse_used + qty
        if projected <= cap:
            return GuardrailResult(rule="warehouse_capacity", passed=True, reason=f"{projected} <= capacity {cap}")
        headroom = max(0, cap - self.ctx.warehouse_used)
        return GuardrailResult(
            rule="warehouse_capacity", passed=False,
            reason=f"projected {projected} exceeds capacity {cap}; clamped to headroom {headroom}", adjusted_qty=headroom,
        )

    # --- Orchestration ----------------------------------------------------- #
    def evaluate(
        self, sku: SKU, proposal: PurchaseProposal, snapshot: InventorySnapshot
    ) -> tuple[int, str, list[GuardrailResult]]:
        """Run all rules over one proposal.

        Returns (final_qty, status, results). Clamps compound (each rule sees the
        qty the previous rule allowed); a hard block wins and forces qty=0.
        Order matters: MOQ first (floor), then the ceilings.
        """
        qty = proposal.proposed_qty
        results: list[GuardrailResult] = []
        status = "approved"

        # Hard block: duplicate PO — refuse regardless of quantity.
        dup = self._rule_duplicate_po(sku)
        results.append(dup)
        if not dup.passed:
            return 0, "rejected", results

        # Floor.
        r = self._rule_moq(sku, qty)
        results.append(r)
        if not r.passed and r.adjusted_qty is not None:
            qty = r.adjusted_qty
            status = "clamped"

        # Ceilings (each further reduces qty).
        for rule in (self._rule_max_units, self._rule_max_order_value, self._rule_budget, self._rule_capacity):
            r = rule(sku, qty) if rule in (self._rule_max_order_value, self._rule_budget) else rule(qty)
            results.append(r)
            if not r.passed:
                if r.adjusted_qty is None or r.adjusted_qty <= 0:
                    return 0, "rejected", results
                qty = min(qty, r.adjusted_qty)
                status = "clamped"

        # Re-check MOQ after clamping: if ceilings pushed us below MOQ, we cannot
        # place a compliant order -> reject.
        if qty < sku.moq:
            results.append(GuardrailResult(
                rule="moq_after_clamp", passed=False,
                reason=f"clamped qty {qty} fell below MOQ {sku.moq}; cannot place compliant order",
            ))
            return 0, "rejected", results

        return qty, status, results
