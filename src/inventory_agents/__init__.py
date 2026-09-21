"""Production Inventory Control — a guardrailed multi-agent system.

A LangGraph multi-agent workflow that turns raw inventory/demand signals into
validated, auditable purchase decisions. The LLM is abstracted behind a
pluggable client so the whole system runs deterministically offline (default)
or against a real LLM when an API key is provided.
"""

__version__ = "0.1.0"
