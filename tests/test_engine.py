"""Engine checks against the demo bakery. Run: python tests/test_engine.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from till import engine as e  # noqa: E402

T, O = e.load_csv(), e.DEMO_OPENING_BALANCE


def test_balance_reconciles():
    assert e.snapshot(T, O)["balance"] == round(O + sum(t["amount"] for t in T), 2)


def test_finds_exactly_the_planted_problems():
    kinds = sorted((a["kind"], a["vendor"]) for a in e.anomalies(T))
    assert kinds == [("duplicate", "Golden Mill Flour Co"), ("new_vendor", "Rapid Oven Repair LLC"),
                     ("price_jump", "City Power and Water"), ("price_jump", "ShiftSlot Scheduling")], kinds


def test_anomaly_ids_are_stable():
    assert [a["id"] for a in e.anomalies(T)] == [a["id"] for a in e.anomalies(list(T))]


def test_monthly_bills_land_on_their_day():
    fc = e.forecast(T, O)
    rent = next(r for r in e.recurring_outflows(T) if r["vendor"] == "Maple St Properties")
    assert rent["cadence"] == "monthly"
    assert e._step(e._d("2026-10-01"), 30).isoformat() == "2026-11-01"
    assert e._step(e._d("2026-01-31"), 30).isoformat() == "2026-02-28"
    assert len(fc["weeks"]) == 13


def test_affordability_is_monotonic():
    lows = [e.affordability(T, O, monthly_cost=m)["low_after"] for m in (0, 500, 1500, 3000)]
    assert lows == sorted(lows, reverse=True), lows
    assert e.affordability(T, O, monthly_cost=0)["verdict"] == "comfortable"
    assert e.affordability(T, O, monthly_cost=3200)["verdict"] == "not yet"


def test_spending_change_defaults_to_last_full_month():
    r = e.spending_change(T)
    assert (r["month"], r["previous"]) == ("2026-09", "2026-08")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("ALL ENGINE CHECKS PASSED")
