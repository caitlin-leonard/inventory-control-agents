"""Central configuration.

All business policy lives here so guardrails and agents read from one source
of truth. Values are deliberately explicit — a reviewer should be able to see
exactly what the system is and isn't allowed to do.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Policy:
    """Business + safety policy the agents operate under."""

    # --- Financial guardrails ---
    purchase_budget_per_cycle: float = 50_000.0   # hard cap on total spend per run
    max_order_value_per_sku: float = 15_000.0     # no single SKU can dominate spend

    # --- Physical guardrails ---
    warehouse_capacity_units: int = 40_000        # on_hand + on_order + new must fit

    # --- Ordering constraints ---
    max_units_per_order: int = 5_000              # blast-radius limit on any one PO
    default_service_level: float = 0.95           # target in-stock probability

    # --- Forecasting ---
    forecast_horizon_days: int = 30
    history_window_days: int = 120

    # --- LLM ---
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "rule_based"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini"))
    llm_max_retries: int = 2                       # structured-output repair attempts


POLICY = Policy()
