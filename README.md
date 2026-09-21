# 🛰️ Production Inventory Control — Guardrailed Multi-Agent System

A **LangGraph multi-agent workflow** that turns raw demand and inventory signals
into **validated, auditable purchase decisions** — with a deterministic
**guardrail layer** that makes it impossible for the agents to over-order, blow
the budget, or overflow the warehouse.

The LLM is abstracted behind a pluggable client, so the entire system **runs
end-to-end offline with no API key** (deterministic backend) *or* against a real
LLM by flipping one env var. That makes it reproducible, CI-testable, and cheap
to demo — while still being production-shaped.

> **Why this project exists.** Most "AI agent" demos are a single prompt in a
> loop. This one shows the parts that actually matter in production: typed state,
> multi-agent orchestration with conditional routing, **structured-output
> contracts**, a **deterministic guardrail engine**, an **evaluation harness**
> that proves the system's safety invariants, and a full test suite.

---

## Architecture

```
                       ┌─────────────┐
   InventoryEvent ───► │   TRIAGE    │  classify + route (analyze / expedite / no_action)
                       └──────┬──────┘
                              │ conditional edge
                   ┌──────────┴───────────┐
                   ▼                      ▼
          ┌─────────────────┐          (END on no_action)
          │ STOCK ANALYSIS  │  forecast demand → EOQ / safety stock / reorder point
          └────────┬────────┘
                   ▼
          ┌─────────────────┐          ┌───────────────────────────┐
          │    PURCHASE     │ ───────► │     GUARDRAIL ENGINE       │
          │  (proposes qty) │ ◄─────── │ budget · capacity · MOQ ·  │
          └────────┬────────┘  clamp/  │ per-order cap · per-SKU $ ·│
                   │           block    │ duplicate-PO               │
                   ▼                    └───────────────────────────┘
            Decision + full audit trail (SQLite + structured trace)
```

**The agents never do arithmetic and are never trusted with safety.** Forecasts
and reorder quantities come from a transparent optimization module; every
proposed order is validated by the guardrail engine before it can become a PO.

## What's inside

| Layer | Module | Highlights |
|---|---|---|
| **Orchestration** | `graph.py` | LangGraph `StateGraph`, typed `GraphState`, conditional routing |
| **Agents** | `agents/` | triage · stock-analysis · purchase, over a pluggable LLM |
| **Forecasting** | `forecasting.py` | auto-selects Holt / simple exp-smoothing / **Croston's** by demand signature |
| **Optimization** | `optimization.py` | EOQ, safety stock via service-level *z*, reorder point |
| **Guardrails** | `guardrails.py` | budget, warehouse capacity, per-order cap, per-SKU value, MOQ, duplicate-PO — **clamp or block** |
| **LLM** | `llm.py` | `RuleBasedLLM` (offline default) + `OpenAIClient` with schema-validation & repair-retry |
| **Persistence** | `db.py` | SQLite: catalog, inventory, sales history, POs, audit log |
| **Service** | `api.py` | FastAPI: `/events`, `/inventory`, `/audit` |
| **Dashboard** | `dashboard/app.py` | Streamlit control tower — see proposals vs. guardrail verdicts live |
| **Evaluation** | `evals/` | adversarial scenarios asserting the safety invariants |
| **Tests** | `tests/` | 19 unit/integration tests |

## Quickstart

```bash
pip install -r requirements.txt
make seed        # generate synthetic seasonal demand for 10 SKUs
make demo        # run a full cycle-review through the multi-agent graph
make test        # 19 tests
make evals       # safety-invariant scorecard
make dashboard   # Streamlit control tower
make api         # FastAPI service
```

No API key is required — the default `rule_based` backend is deterministic. To
use a real LLM: `pip install langchain-openai`, then set `LLM_PROVIDER=openai`
and `OPENAI_API_KEY` (see `.env.example`).

## Sample run

```
=== Event: cycle_review  |  route: analyze ===
Analyzed 10 SKUs; 7 below reorder point.

  [CLMP] SKU-1010: qty= 5000  $ 5,000   order 5062 (EOQ 2531) to restore cover.
         ! max_units_per_order: requested 5062 exceeds per-order cap 5000; clamped
  [OK ] SKU-1005: qty= 1116  $ 6,696
  [CLMP] SKU-1007: qty=  333  $14,985
         ! max_order_value_per_sku: $16,650 exceeds per-SKU value cap $15,000; clamped
  [CLMP] SKU-1002: qty=  472  $ 3,776
         ! budget_cap: $13,856 exceeds remaining budget $3,780; clamped

Committed $49,996 / $50,000 budget; 0 rejected/blocked.
Trace: triage -> stock_analysis -> purchase
```

Three different guardrails fire, the batch respects the global budget, and the
whole decision is written to an audit log.

## Evaluation

`make evals` runs adversarial scenarios and asserts the system's invariants:

| Scenario | Invariant checked |
|---|---|
| `stockout_triggers_reorder` | a clear stockout risk **must** produce an order |
| `overorder_is_clamped` | a huge demand spike **cannot** breach the per-order cap |
| `budget_is_respected` | 20 hungry SKUs **cannot** exceed the cycle budget |
| `healthy_stock_no_order` | well-stocked SKUs get **no** order |

```
4/4 scenarios passed
```

## Design decisions worth calling out

- **Guardrails are deterministic, not prompted.** Safety is enforced in code and
  unit-tested, so it holds regardless of model behavior — the property that makes
  an agent system deployable.
- **Structured output as a contract.** Agents must return Pydantic-validated
  objects; the real-LLM backend repairs invalid output on a bounded retry loop.
- **Batch-aware budgeting.** The purchase agent commits budget and warehouse
  headroom as it goes and prioritizes the deepest stockout risk first, so scarce
  budget protects the highest-risk SKUs.
- **Forecast method is chosen, not fixed.** Intermittent (spare-part) demand uses
  Croston's; smooth/trending demand uses exponential smoothing / Holt.

## Tech stack

Python · LangGraph · LangChain-Core · Pydantic v2 · FastAPI · Streamlit · SQLite ·
pytest. Optional: langchain-openai for the real-LLM backend.

## Project layout

```
src/inventory_agents/   # library: graph, agents, forecasting, optimization, guardrails, llm, db, api
dashboard/              # Streamlit control tower
evals/                  # scenario-based safety evaluation
tests/                  # pytest suite
data/                   # synthetic data generator
```

---

*Built as a portfolio project demonstrating production-grade agentic AI:
multi-agent orchestration, structured outputs, deterministic guardrails,
evaluation, and observability.*
