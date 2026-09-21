"""Streamlit control tower for the inventory agents.

Run:  streamlit run dashboard/app.py

Shows live stock positions, lets you fire an event through the multi-agent
graph, and renders the resulting purchase orders with their guardrail verdicts —
so a reviewer can *see* the "agent proposed X, guardrail clamped/blocked it to Y"
story that makes this project distinctive.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from inventory_agents import db  # noqa: E402
from inventory_agents.graph import run_event  # noqa: E402
from inventory_agents.schemas import EventType, InventoryEvent  # noqa: E402

st.set_page_config(page_title="Inventory Control Agents", layout="wide", page_icon="🛰️")
db.init_db()

# --- gothic-neon theme (black base · pink · neon green) --------------------- #
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@600;800&display=swap');

.stApp { background:
    radial-gradient(1200px 600px at 15% -10%, #1a0f1f 0%, #0d0710 55%, #080409 100%); }

h1 {
    font-family:'Orbitron',sans-serif !important; font-weight:800 !important;
    color:#ff5fa2 !important;
    text-shadow:0 0 8px rgba(255,95,162,.55), 0 0 22px rgba(255,95,162,.25);
    letter-spacing:1px;
}
h2, h3 { font-family:'Orbitron',sans-serif !important; color:#d9b8ff !important;
    text-shadow:0 0 6px rgba(176,108,255,.35); }
body, p, label, .stMarkdown, span { font-family:'Share Tech Mono',monospace !important; }

/* neon-green primary button */
.stButton > button {
    background:transparent; color:#8affc1; border:1.5px solid #8affc1;
    border-radius:10px; font-family:'Share Tech Mono',monospace; font-size:15px;
    box-shadow:0 0 8px rgba(138,255,193,.35); transition:all .18s ease;
}
.stButton > button:hover {
    background:#8affc1; color:#0d0710;
    box-shadow:0 0 16px rgba(138,255,193,.75); transform:translateY(-1px);
}

/* success banner -> neon-green glass */
div[data-testid="stAlert"] {
    background:rgba(138,255,193,.06) !important; border:1px solid #8affc1 !important;
    border-radius:12px; box-shadow:0 0 14px rgba(138,255,193,.25);
}
div[data-testid="stAlert"] * { color:#8affc1 !important; }

/* dataframe frame glow */
div[data-testid="stDataFrame"] {
    border:1px solid #3a2145; border-radius:12px; padding:2px;
    box-shadow:0 0 18px rgba(176,108,255,.18);
}
/* inputs */
div[data-baseweb="select"] > div, .stMultiSelect div[data-baseweb="select"] > div {
    background:#160b1a !important; border:1px solid #7a3fd1 !important; border-radius:10px;
}
hr { border-color:#3a2145; }
</style>
""", unsafe_allow_html=True)

st.title("🛰 PRODUCTION INVENTORY CONTROL")
st.markdown("<p style='color:#ff9ecb;margin-top:-14px;letter-spacing:3px;'>"
            "◈ AGENT CONTROL TOWER · guardrailed multi-agent system ◈</p>",
            unsafe_allow_html=True)

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Fire an event")
    event_type = st.selectbox("Event type", [e.value for e in EventType])
    skus = list(db.get_skus().keys())
    chosen = st.multiselect("SKUs (empty = all)", skus)
    run = st.button("Run agents ▶")

with col2:
    st.subheader("Current inventory")
    inv = db.get_inventory()
    skus_meta = db.get_skus()
    inv_df = pd.DataFrame([
        {"SKU": k, "name": skus_meta[k].name, "on_hand": v.on_hand, "on_order": v.on_order,
         "position": v.on_hand + v.on_order}
        for k, v in inv.items()
    ])
    st.dataframe(inv_df, use_container_width=True, hide_index=True)

if run:
    state = run_event(InventoryEvent(event_type=EventType(event_type), sku_ids=chosen))
    decision = state["decision"]
    st.success(f"Route: {decision.triage_route} · "
               f"committed ${decision.total_committed_spend:,.0f} · "
               f"{decision.rejected_count} rejected/blocked")

    st.subheader("Purchase decisions")
    rows = []
    for po in decision.purchase_orders:
        failed = "; ".join(f"{g.rule}: {g.reason}" for g in po.guardrails if not g.passed) or "—"
        rows.append({"SKU": po.sku_id, "status": po.status, "qty": po.qty,
                     "value $": round(po.order_value), "guardrails fired": failed})

    if not rows:
        st.info("No SKUs are below their reorder point — nothing to order. "
                "Run `make seed` in the terminal to reset stock, then fire an event again.")
    else:
        df = pd.DataFrame(rows)

        def _status_style(val):
            colors = {"approved": "#8affc1", "clamped": "#ff5fa2", "rejected": "#ff5a6e"}
            c = colors.get(val, "#f5e9f2")
            return f"color:{c};font-weight:bold;text-shadow:0 0 6px {c}66;"

        styled = df.style.map(_status_style, subset=["status"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

        st.subheader("Agent trace")
        if st.checkbox("Show agent trace", value=True):
            st.json(state.get("trace", []))
