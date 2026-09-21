"""Generate a realistic synthetic dataset: SKUs with seasonal + noisy demand.

Creates a mix of demand signatures so the forecasting engine has to choose
methods intelligently:
- fast movers (smooth, trending),
- seasonal movers (weekly cycle),
- intermittent / spare parts (mostly-zero demand).

Run:  python -m data.generate_data
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inventory_agents import db  # noqa: E402
from inventory_agents.config import POLICY  # noqa: E402

random.seed(42)

CATEGORIES = ["electronics", "consumables", "spare_parts", "packaging"]

SKUS = [
    # sku_id, name, category, unit_cost, lead_time, moq, order_cost, holding_rate, profile
    ("SKU-1001", "USB-C Cable 1m", "electronics", 2.5, 7, 200, 75, 0.25, "fast"),
    ("SKU-1002", "Wireless Mouse", "electronics", 8.0, 14, 100, 120, 0.22, "seasonal"),
    ("SKU-1003", "Thermal Paste 5g", "consumables", 1.2, 5, 500, 60, 0.30, "fast"),
    ("SKU-1004", "HDMI Adapter", "electronics", 4.5, 10, 150, 90, 0.25, "seasonal"),
    ("SKU-1005", "Cooling Fan 120mm", "spare_parts", 6.0, 21, 50, 100, 0.20, "intermittent"),
    ("SKU-1006", "Shipping Box M", "packaging", 0.8, 4, 1000, 50, 0.35, "fast"),
    ("SKU-1007", "PSU 650W", "spare_parts", 45.0, 28, 20, 150, 0.18, "intermittent"),
    ("SKU-1008", "Screen Protector", "consumables", 1.5, 9, 300, 70, 0.28, "seasonal"),
    ("SKU-1009", "Laptop Stand", "electronics", 12.0, 18, 60, 110, 0.20, "seasonal"),
    ("SKU-1010", "Cable Ties 100pk", "packaging", 1.0, 6, 400, 55, 0.32, "fast"),
]


def demand_series(profile: str, days: int) -> list[float]:
    out = []
    base = {"fast": 40, "seasonal": 25, "intermittent": 0}[profile]
    for d in range(days):
        if profile == "fast":
            trend = base + 0.05 * d
            season = 5 * math.sin(2 * math.pi * d / 7)
            val = max(0, random.gauss(trend + season, 6))
        elif profile == "seasonal":
            season = 15 * max(0, math.sin(2 * math.pi * d / 30))  # monthly peak
            weekly = 6 * math.sin(2 * math.pi * d / 7)
            val = max(0, random.gauss(base + season + weekly, 5))
        else:  # intermittent
            val = random.choice([0, 0, 0, 0, random.randint(5, 30)])
        out.append(round(val, 1))
    return out


def main(db_path=db.DEFAULT_DB):
    db.init_db(db_path)
    days = POLICY.history_window_days
    with db.connect(db_path) as c:
        c.execute("DELETE FROM skus"); c.execute("DELETE FROM inventory")
        c.execute("DELETE FROM sales_history"); c.execute("DELETE FROM purchase_orders")
        c.execute("DELETE FROM audit_log")
        for sid, name, cat, cost, lt, moq, oc, hr, profile in SKUS:
            c.execute(
                "INSERT INTO skus VALUES (?,?,?,?,?,?,?,?)",
                (sid, name, cat, cost, lt, moq, oc, hr),
            )
            series = demand_series(profile, days)
            for day, units in enumerate(series):
                c.execute("INSERT INTO sales_history VALUES (?,?,?)", (sid, day, units))
            # Seed inventory deliberately low for some SKUs to trigger reorders.
            recent = sum(series[-14:]) / 14
            on_hand = int(recent * random.choice([2, 5, 10, 15]))  # some below ROP
            c.execute("INSERT INTO inventory VALUES (?,?,?)", (sid, on_hand, 0))
    print(f"Seeded {len(SKUS)} SKUs x {days} days of history at {db_path}")


if __name__ == "__main__":
    main()
