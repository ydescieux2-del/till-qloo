"""Minimal Qloo Insights client for the hackathon environment.

    QLOO_API_KEY set    -> live GET https://hackathon.api.qloo.com/v2/insights (header X-Api-Key)
    QLOO_API_KEY unset  -> MOCK mode: a synthetic fixture shaped like the documented Insights response

Mock data is invented for the demo (fictional places). It is never real Qloo output, and live Qloo responses are
only cached in memory on the server, never written to disk or the repo (Qloo's hackathon data-use rule).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

DEFAULT_BASE = "https://hackathon.api.qloo.com"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mock_insights_places.json"
MOCK_NOTE = "Demo data until the Qloo key is set"
LIVE_NOTE = "Live Qloo Insights data"

_cache: dict[tuple, dict] = {}


class QlooError(RuntimeError):
    pass


def base_url() -> str:
    return os.environ.get("QLOO_BASE_URL", DEFAULT_BASE).rstrip("/")


def is_live() -> bool:
    return bool(os.environ.get("QLOO_API_KEY", "").strip())


def source() -> dict:
    """What the UI shows next to every taste result."""
    return {"live": is_live(), "label": LIVE_NOTE if is_live() else MOCK_NOTE}


def insights(params: dict) -> dict:
    """GET /v2/insights. Parameters go in the query string (the endpoint is GET only).
    Returns the parsed JSON body: {"success": bool, "results": {"entities": [...]}, ...}."""
    clean = {k: v for k, v in params.items() if v not in (None, "", [])}
    if "filter.type" not in clean:
        raise ValueError("filter.type is required for every Insights request")
    key = tuple(sorted((k, str(v)) for k, v in clean.items()))
    if key in _cache:
        return _cache[key]
    body = _live(clean) if is_live() else _mock(clean)
    _cache[key] = body
    return body


def _live(params: dict) -> dict:
    try:
        r = httpx.get(f"{base_url()}/v2/insights", params=params, timeout=20,
                      headers={"X-Api-Key": os.environ["QLOO_API_KEY"].strip(), "accept": "application/json"})
    except httpx.HTTPError as exc:
        raise QlooError(f"Could not reach Qloo: {exc}") from exc
    if r.status_code != 200:
        raise QlooError(f"Qloo returned {r.status_code}: {r.text[:200]}")
    body = r.json()
    if not body.get("success", True):
        raise QlooError(f"Qloo request failed: {str(body)[:200]}")
    return body


def _mock(params: dict) -> dict:
    """Deterministic stand-in for the live call. Honors filter.tags (an entity must carry every tag) and
    take, so tools exercise the same code path they will use live."""
    body = json.loads(FIXTURE.read_text())
    ents = body["results"]["entities"]
    if params.get("filter.tags"):
        want = {t.strip() for t in str(params["filter.tags"]).split(",") if t.strip()}
        ents = [e for e in ents if want <= {t["id"] for t in e.get("tags", [])}]
    take = int(params.get("take", 20))
    body["results"]["entities"] = ents[:take]
    return body


def places(neighborhood: str, *, age: str | None = None, audiences: str | None = None,
           tags: str | None = None, take: int = 30) -> list[dict]:
    """Places in a neighborhood, ranked by Qloo affinity for the given audience signals."""
    body = insights({"filter.type": "urn:entity:place", "filter.location.query": neighborhood,
                     "filter.tags": tags, "signal.demographics.age": age,
                     "signal.demographics.audiences": audiences, "take": max(1, min(int(take), 50))})
    return (body.get("results") or {}).get("entities") or []
