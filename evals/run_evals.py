"""Run all evaluation scenarios and print a scorecard.

Run:  python -m evals.run_evals
Exits non-zero if any invariant fails (CI-friendly).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evals.scenarios import SCENARIOS  # noqa: E402
from inventory_agents.graph import run_event  # noqa: E402


def main() -> int:
    passed = 0
    print("\nInventory Agents — Evaluation Scorecard")
    print("=" * 55)
    for sc in SCENARIOS:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "eval.db"
            sc.setup(db_path)
            state = run_event(sc.event, db_path=db_path)
            ok, msg = sc.check(state["decision"])
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {sc.name}")
        if not ok:
            print(f"        -> {msg}")
        passed += ok
    print("=" * 55)
    print(f"{passed}/{len(SCENARIOS)} scenarios passed\n")
    return 0 if passed == len(SCENARIOS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
