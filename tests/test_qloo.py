"""Qloo client and the three taste tools, against the synthetic fixture. Run: python tests/test_qloo.py

No network and no key needed. The live-request test swaps httpx.get for a fake to check the exact URL,
header, and query string Till will send once QLOO_API_KEY is set.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.pop("QLOO_API_KEY", None)
os.environ["TILL_DB"] = str(Path(tempfile.mkdtemp()) / "test_state.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from till import engine, qloo, server, taste  # noqa: E402

HP = "Highland Park, Los Angeles"
BRUNCH = "urn:tag:dining_options:place:brunch"


def _fresh():
    qloo._cache.clear()
    os.environ.pop("QLOO_API_KEY", None)


# ---------------------------------------------------------------- client

def test_mock_mode_without_key():
    _fresh()
    assert not qloo.is_live() and qloo.source()["label"] == qloo.MOCK_NOTE
    body = qloo.insights({"filter.type": "urn:entity:place", "filter.location.query": HP})
    assert body["success"] is True and len(body["results"]["entities"]) == 12
    e = body["results"]["entities"][0]
    assert {"name", "entity_id", "type", "subtype", "properties", "popularity", "tags", "query"} <= set(e)
    assert e["type"] == "urn:entity" and e["subtype"] == "urn:entity:place" and "affinity" in e["query"]


def test_mock_honors_filter_tags_and_take():
    _fresh()
    brunch = qloo.places(HP, tags=BRUNCH)
    assert brunch and all(BRUNCH in {t["id"] for t in e["tags"]} for e in brunch)
    assert len(qloo.places(HP, take=3)) == 3


def test_filter_type_required():
    _fresh()
    try:
        qloo.insights({"filter.location.query": HP})
    except ValueError:
        return
    raise AssertionError("missing filter.type should raise")


def test_live_request_shape(monkeypatch=None):
    _fresh()
    seen = {}

    class Resp:
        status_code = 200
        text = ""

        def json(self):
            return json.loads(qloo.FIXTURE.read_text())

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers)
        return Resp()

    real = qloo.httpx.get
    os.environ["QLOO_API_KEY"] = "test-key-not-real"
    qloo.httpx.get = fake_get
    try:
        qloo.places(HP, age="25_to_29", tags=BRUNCH)
    finally:
        qloo.httpx.get = real
        _fresh()
    assert seen["url"] == "https://hackathon.api.qloo.com/v2/insights", seen["url"]
    assert seen["headers"]["X-Api-Key"] == "test-key-not-real"
    assert seen["params"]["filter.type"] == "urn:entity:place"
    assert seen["params"]["filter.location.query"] == HP
    assert seen["params"]["filter.tags"] == BRUNCH and seen["params"]["signal.demographics.age"] == "25_to_29"
    assert "signal.demographics.audiences" not in seen["params"]   # empty params are not sent


def test_live_errors_are_not_masked_by_mock():
    _fresh()

    class Resp:
        status_code = 401
        text = "No API key found in request"

    real = qloo.httpx.get
    os.environ["QLOO_API_KEY"] = "bad"
    qloo.httpx.get = lambda *a, **k: Resp()
    try:
        out = server.neighborhood_taste(HP)
    finally:
        qloo.httpx.get = real
        _fresh()
    assert out.is_error and "401" in out.content[0].text


# ---------------------------------------------------------------- tools

def test_neighborhood_taste():
    _fresh()
    out = server.neighborhood_taste(HP, age="25_to_29,30_to_34,nonsense")
    sc = out.structured_content
    assert not out.is_error
    assert sc["taste"][0]["name"] == "Brunch", sc["taste"][0]
    assert all(0 < t["weight"] <= 1 for t in sc["taste"])
    assert sc["card"]["kind"] == "taste" and sc["card"]["badge"]["text"] == qloo.MOCK_NOTE
    assert "demo data until the Qloo key is set" in out.content[0].text
    assert server._ages("25_to_29,nonsense") == "25_to_29"


def test_launch_ideas_ranked_by_local_affinity():
    _fresh()
    out = server.launch_ideas(HP)
    ideas = out.structured_content["ideas"]
    assert ideas[0]["id"] == "sunday_brunch", ideas
    fits = [i["fit"] for i in ideas]
    assert fits == sorted(fits, reverse=True) and all(0 <= f <= 100 for f in fits)
    assert ideas[-1]["id"] == "sourdough_wine_night"


def test_without_qloo_signal_nothing_is_recommended():
    """The judging test in code: with no Qloo entities, every idea scores 0 and Till refuses to guess."""
    assert all(i["fit"] == 0 for i in taste.rank_ideas([]))
    assert taste.profile([]) == []
    assert taste.local_price_level([]) is None


def test_profile_skips_logistics_tags():
    # Live Qloo tags almost every place "Wheelchair accessible entrance"; that is not a taste.
    tag = lambda kind, name: {"id": f"urn:tag:{kind}:qloo:{name.lower()}", "name": name, "type": f"urn:tag:{kind}:qloo"}
    ents = [{"query": {"affinity": 0.8}, "tags": [tag("accessibility", "Wheelchair accessible entrance"),
                                                  tag("ambience", "Casual"), tag("decor", "Casual"),
                                                  tag("cuisine", "Mexican")]}]
    assert [r["name"] for r in taste.profile(ents)] == ["Casual", "Mexican"]


def test_price_the_idea_uses_engine_and_local_price():
    _fresh()
    out = server.price_the_idea("sunday_brunch", HP)
    sc = out.structured_content
    p, r = sc["pricing"], sc["affordability"]
    comps = qloo.places(HP, tags=BRUNCH, take=20)
    price = engine.price_per_cover(taste.local_price_level(comps))
    assert price == 22                                      # median brunch price level 2 in the fixture
    i = taste.idea("sunday_brunch")
    assert p == engine.price_idea(i["one_time_cost"], i["staff_hours_per_week"], i["other_weekly_cost"],
                                  i["food_cost_pct"], price)
    txns, opening = engine.load_csv(), engine.DEMO_OPENING_BALANCE
    assert r == engine.affordability(txns, opening, monthly_cost=p["monthly_cost"], one_time_cost=p["one_time_cost"],
                                     floor=server.DEFAULT_FLOOR)
    assert r["verdict"] == "tight" and r["low_after"] < r["low_before"]
    busy = server.price_the_idea("sunday_brunch", HP, covers_per_week=40).structured_content["affordability"]
    assert busy["low_after"] > r["low_after"]


def test_price_the_idea_unknown_id():
    assert server.price_the_idea("nope").is_error


def test_engine_price_math():
    p = engine.price_idea(1000, 10, 80, 0.30, 20.0)
    assert p["fixed_weekly"] == 300.0 and p["margin_per_cover"] == 14.0
    assert p["break_even_covers_per_week"] == 21.4 and p["monthly_cost"] == 1300.0
    assert engine.price_idea(0, 10, 80, 0.30, 20.0, covers_per_week=30)["monthly_cost"] == round((300 - 420) * 52 / 12, 2)
    assert [engine.price_per_cover(x) for x in (None, 1, 1.5, 2, 4, 9)] == [22, 14, 18, 22, 52, 52]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("ALL QLOO CHECKS PASSED")
