"""Turn Qloo place results into a neighborhood taste profile and rank launch ideas against it.

Deterministic, stdlib only. Qloo supplies the signal (which places this audience has affinity for in this
neighborhood, and what those places are tagged with). This module only aggregates and ranks. Money is not
computed here; see engine.price_idea.
"""
from __future__ import annotations

from statistics import median

# Launch ideas a small bakery could run. Costs are planning assumptions the owner can override; they are
# inputs to engine.price_idea, not outputs of any model. `match` words are compared to Qloo tag names.
IDEAS = [
    {"id": "sunday_brunch", "title": "Sunday brunch: conchas, chilaquiles, cafe de olla", "kind": "menu",
     "match": ["brunch", "mexican", "latin", "coffee"], "comparable_tag": "urn:tag:dining_options:place:brunch",
     "one_time_cost": 1_200, "staff_hours_per_week": 12, "other_weekly_cost": 60, "food_cost_pct": 0.32},
    {"id": "pan_dulce_box", "title": "Weekend pan dulce preorder box", "kind": "product",
     "match": ["bakery", "mexican", "dessert"], "comparable_tag": "urn:tag:category:place:bakery",
     "one_time_cost": 400, "staff_hours_per_week": 5, "other_weekly_cost": 35, "food_cost_pct": 0.28},
    {"id": "vegan_pastry", "title": "Vegan pastry and oat latte flight", "kind": "menu",
     "match": ["vegan", "coffee", "vegetarian", "healthy"], "comparable_tag": "urn:tag:offerings:place:vegan_options",
     "one_time_cost": 500, "staff_hours_per_week": 4, "other_weekly_cost": 40, "food_cost_pct": 0.35},
    {"id": "kids_cookie_class", "title": "Saturday kids' cookie decorating class", "kind": "event",
     "match": ["kids", "family", "dessert"], "comparable_tag": "urn:tag:children:place:good_for_kids",
     "one_time_cost": 350, "staff_hours_per_week": 4, "other_weekly_cost": 45, "food_cost_pct": 0.20},
    {"id": "sourdough_wine_night", "title": "Friday sourdough and natural wine night", "kind": "event",
     "match": ["wine", "bar", "cocktail"], "comparable_tag": "urn:tag:category:place:wine_bar",
     "one_time_cost": 2_400, "staff_hours_per_week": 8, "other_weekly_cost": 120, "food_cost_pct": 0.38},
]


def idea(idea_id: str) -> dict | None:
    return next((i for i in IDEAS if i["id"] == idea_id), None)


def _affinity(e: dict) -> float:
    q = e.get("query") or {}
    a = q.get("affinity")
    if a is None:
        a = e.get("popularity", 1.0)
    return max(0.0, float(a))


# Tag families that describe logistics, not taste. Live Qloo tags nearly every place with these
# (wheelchair entrance, credit cards, street parking), so they would crowd out what people actually like.
NOT_TASTE = {"accessibility", "payments", "credit_card", "amenities", "parking", "service_type", "service_options",
             "planning", "age_range", "genre", "activity_type", "customer_identity", "gender", "audience"}


def _is_taste(tag: dict) -> bool:
    parts = str(tag.get("type") or tag.get("id", "")).split(":")
    return not (len(parts) > 2 and parts[2] in NOT_TASTE)


def profile(entities: list[dict], top: int = 8) -> list[dict]:
    """Tags weighted by the Qloo affinity of the places that carry them, as a share of total affinity
    (0 to 1). A tag on every high-affinity place scores near 1. Logistics tags (NOT_TASTE) are left out."""
    total = sum(_affinity(e) for e in entities)
    if not total:
        return []
    acc: dict[str, dict] = {}
    for e in entities:
        a = _affinity(e)
        for t in filter(_is_taste, e.get("tags") or []):
            row = acc.setdefault(t["id"], {"id": t["id"], "name": t.get("name", t["id"]), "type": t.get("type", ""),
                                           "weight": 0.0, "places": 0})
            row["weight"] += a
            row["places"] += 1
    rows, seen = [], set()
    for r in sorted(acc.values(), key=lambda r: (-r["weight"], r["name"])):
        if r["name"].lower() in seen:   # "Casual" ambience and "Casual" decor read as one trait out loud
            continue
        seen.add(r["name"].lower())
        rows.append({**r, "weight": round(r["weight"] / total, 3)})
    return rows[:top]


def _matches(word: str, tag_name: str) -> bool:
    return word.lower() in tag_name.lower()


def rank_ideas(entities: list[dict]) -> list[dict]:
    """Score each idea 0 to 100 by local fit: the share of neighborhood affinity carried by places tagged
    with any of the idea's words. With no Qloo signal every idea scores 0, so nothing can be recommended."""
    total = sum(_affinity(e) for e in entities)
    out = []
    for i in IDEAS:
        hits, matched = 0.0, set()
        for e in entities:
            names = [t.get("name", "") for t in e.get("tags") or []]
            m = {w for w in i["match"] for n in names if _matches(w, n)}
            if m:
                hits += _affinity(e)
                matched |= m
        fit = round(100 * hits / total) if total else 0
        out.append({**i, "fit": fit, "matched": sorted(matched)})
    out.sort(key=lambda r: (-r["fit"], r["id"]))
    return out


def local_price_level(entities: list[dict]) -> float | None:
    """Median Qloo price level (1 to 4) of comparable places, or None if Qloo returned none."""
    levels = [e.get("properties", {}).get("price_level") for e in entities]
    levels = [float(x) for x in levels if isinstance(x, (int, float))]
    return median(levels) if levels else None
