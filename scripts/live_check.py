"""Live Qloo check: run once the hackathon key arrives, before tuning anything.

    .venv/bin/python scripts/live_check.py            # key from env or the gitignored .env
    .venv/bin/python scripts/live_check.py --neighborhood "Echo Park, Los Angeles"

Makes 5 real GET requests that mirror Till's taste tools, prints which fields the live responses carry, and flags
every place the live shape differs from the mock fixture (till/fixtures/mock_insights_places.json) so tuning is
fast. Live responses are printed only, never written to disk (Qloo hackathon data-use rule).

Without QLOO_API_KEY it prints a message and exits 0 without touching the network.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

AGE = "25_to_29,30_to_34"
CONTROL = "Brooklyn, New York"  # far from the default neighborhood: tests whether the location filter bites


def load_dotenv() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


FLAGS: list[str] = []


def flag(msg: str) -> None:
    FLAGS.append(msg)
    print(f"  MISMATCH: {msg}")


def get(path: str, params: dict) -> dict | None:
    import httpx
    from till import qloo
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    url = f"{qloo.base_url()}{path}"
    print(f"\nGET {path} {clean}")
    try:
        r = httpx.get(url, params=clean, timeout=25,
                      headers={"X-Api-Key": os.environ["QLOO_API_KEY"].strip(), "accept": "application/json"})
    except httpx.HTTPError as exc:
        flag(f"{path}: network error {exc}")
        return None
    print(f"  status {r.status_code}")
    if r.status_code != 200:
        flag(f"{path} {clean}: HTTP {r.status_code} {r.text[:300]}")
        return None
    body = r.json()
    if body.get("success") is False:
        flag(f"{path}: success=false {str(body)[:300]}")
    return body


def entities(body: dict | None) -> list[dict]:
    return ((body or {}).get("results") or {}).get("entities") or []


def find_keys(obj, needle: str, prefix: str = "") -> set[str]:
    """Dotted paths of every key containing `needle` (for finding where price lives)."""
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            if needle in k.lower():
                out.add(p)
            out |= find_keys(v, needle, p)
    elif isinstance(obj, list) and obj:
        out |= find_keys(obj[0], needle, prefix + "[]")
    return out


def describe(ents: list[dict], fixture_ents: list[dict]) -> None:
    print(f"  entities: {len(ents)}")
    if not ents:
        flag("no entities returned; check filter.location.query spelling or try filter.location with coordinates")
        return
    live_top = Counter(k for e in ents for k in e)
    mock_top = {k for e in fixture_ents for k in e}
    print(f"  top-level keys: {sorted(live_top)}")
    for k in sorted(mock_top - set(live_top)):
        if k != "disambiguation":
            flag(f"fixture entities carry '{k}', live ones don't")
    live_props = Counter(k for e in ents for k in (e.get("properties") or {}))
    print(f"  properties keys (count of {len(ents)}): {dict(live_props.most_common(25))}")
    aff = [((e.get("query") or {}).get("affinity")) for e in ents]
    n_aff = sum(a is not None for a in aff)
    print(f"  query.affinity present on {n_aff}/{len(ents)}"
          + (f", range {min(a for a in aff if a is not None)} to {max(a for a in aff if a is not None)}" if n_aff else ""))
    if n_aff < len(ents):
        flag(f"query.affinity missing on {len(ents) - n_aff} entities; taste._affinity falls back to popularity")
    pl = [(e.get("properties") or {}).get("price_level") for e in ents]
    n_pl = sum(isinstance(x, (int, float)) for x in pl)
    print(f"  properties.price_level numeric on {n_pl}/{len(ents)}: {Counter(pl).most_common()}")
    if n_pl == 0:
        where = set().union(*(find_keys(e, "price") for e in ents))
        flag(f"no numeric properties.price_level; price-like fields found at: {sorted(where) or 'none'}")
    tags = Counter((t.get("id"), t.get("name"), t.get("type")) for e in ents for t in (e.get("tags") or []))
    print(f"  distinct tags: {len(tags)}; top 20:")
    for (tid, name, typ), c in tags.most_common(20):
        print(f"    {c:>3}  {name!r:32} {tid}  ({typ})")
    if not tags:
        flag("entities carry no tags; taste.profile and rank_ideas will score 0")
    print("  first 5 by order returned:")
    for e in ents[:5]:
        p = e.get("properties") or {}
        print(f"    {e.get('name')!r:36} affinity={(e.get('query') or {}).get('affinity')} "
              f"price_level={p.get('price_level')} address={str(p.get('address'))[:60]!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--neighborhood", default=None)
    args = ap.parse_args()
    load_dotenv()
    if not os.environ.get("QLOO_API_KEY", "").strip():
        print("QLOO_API_KEY is not set (checked the environment and ~/till-qloo/.env).\n"
              "Nothing was sent. Add the key with the add-key skill, then rerun:\n"
              "  .venv/bin/python scripts/live_check.py")
        return 0

    from till import qloo, taste
    from till.server import DEFAULT_NEIGHBORHOOD
    hood = args.neighborhood or DEFAULT_NEIGHBORHOOD
    fixture = entities(json.loads(qloo.FIXTURE.read_text()))
    print(f"Qloo live check against {qloo.base_url()}  neighborhood={hood!r}  (key from env, not printed)")

    # 1. neighborhood_taste: places in the neighborhood, audience by age
    print("\n=== 1. neighborhood_taste (filter.location.query + signal.demographics.age) ===")
    b1 = get("/v2/insights", {"filter.type": "urn:entity:place", "filter.location.query": hood,
                               "signal.demographics.age": AGE, "take": 30})
    e1 = entities(b1)
    describe(e1, fixture)
    if e1:
        prof = taste.profile(e1)
        print("  taste.profile ->", [(p["name"], p["weight"]) for p in prof])

    # 2. launch_ideas: same request without the age signal, then rank
    print("\n=== 2. launch_ideas (no audience signal) ===")
    b2 = get("/v2/insights", {"filter.type": "urn:entity:place", "filter.location.query": hood, "take": 30})
    e2 = entities(b2)
    describe(e2, fixture)
    if e2:
        ranked = taste.rank_ideas(e2)
        print("  rank_ideas ->", [(r["id"], r["fit"], r["matched"]) for r in ranked])
        names = {t.get("name", "").lower() for e in e2 for t in (e.get("tags") or [])}
        ids = {t.get("id") for e in e2 for t in (e.get("tags") or [])}
        for i in taste.IDEAS:
            dead = [w for w in i["match"] if not any(w in n for n in names)]
            if len(dead) == len(i["match"]):
                flag(f"idea {i['id']}: none of its match words {dead} hit a live tag name")
            elif dead:
                print(f"  note: idea {i['id']} match words {dead} hit no live tag name (others do)")
            if i["comparable_tag"] not in ids:
                print(f"  note: comparable_tag {i['comparable_tag']} ({i['id']}) not on any of these places")
        if all(r["fit"] == 0 for r in ranked):
            flag("every idea scores 0 on live data; tune taste.IDEAS match words to the real tag names above")

    # 3. location filter control: a far neighborhood should return different places
    print(f"\n=== 3. location filter control ({CONTROL}) ===")
    e3 = entities(get("/v2/insights", {"filter.type": "urn:entity:place", "filter.location.query": CONTROL,
                                       "take": 30}))
    print(f"  entities: {len(e3)}")
    if e2 and e3:
        overlap = len({e.get("entity_id") for e in e2} & {e.get("entity_id") for e in e3})
        print(f"  overlap with request 2: {overlap}/{len(e2)}")
        if overlap > len(e2) // 2:
            flag("filter.location.query does not seem to filter (results barely change across cities); "
                 "try filter.location=POINT(lon lat) with filter.location.radius")
        else:
            print("  location filter works (results change by place)")

    # 4. price_the_idea: comparable places by tag, median price level
    print("\n=== 4. price_the_idea (filter.tags = brunch) ===")
    brunch = taste.idea("sunday_brunch")["comparable_tag"]
    e4 = entities(get("/v2/insights", {"filter.type": "urn:entity:place", "filter.location.query": hood,
                                       "filter.tags": brunch, "take": 20}))
    describe(e4, fixture)
    if e4 is not None:
        lvl = taste.local_price_level(e4)
        print(f"  local_price_level -> {lvl}")
        missing = [e.get("name") for e in e4 if brunch not in {t.get("id") for t in e.get("tags") or []}]
        if missing:
            flag(f"{len(missing)} comparable places don't list {brunch} in tags (filter.tags semantics differ "
                 f"from the mock, which requires every tag): {missing[:5]}")
        if lvl is None:
            flag("no price level on comparable places; price_per_cover falls back to the level-2 default")

    # 5. real tag ids for the idea themes (the mock's ids are educated guesses)
    print("\n=== 5. tag lookup (/v2/tags?filter.query=brunch) ===")
    b5 = get("/v2/tags", {"filter.query": "brunch", "take": 10})
    tags5 = ((b5 or {}).get("results") or {}).get("tags") or []
    for t in tags5[:10]:
        print(f"    {t.get('name')!r:32} {t.get('id') or t.get('tag_id')}  ({t.get('type')})")
    if b5 is not None and not tags5:
        print(f"  no results.tags; top-level keys: {sorted(b5)}; results keys: {sorted((b5.get('results') or {}))}")
    if tags5 and brunch not in {t.get("id") or t.get("tag_id") for t in tags5}:
        flag(f"{brunch} is not among Qloo's brunch tags above; update taste.IDEAS comparable_tag")

    print("\n=== Summary ===")
    if FLAGS:
        print(f"{len(FLAGS)} mismatch(es) to tune:")
        for f in FLAGS:
            print(f"  - {f}")
        return 1
    print("Live responses match the shape Till expects. Rerun the demo story and update the numbers in "
          "SUBMISSION_DRAFT.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
