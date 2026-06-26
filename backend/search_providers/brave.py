"""Provider Brave Search (Phase 6.1).

Clé via BRAVE_SEARCH_API_KEY. Sans clé -> []. Toute erreur -> [].
"""
from __future__ import annotations

import os
import urllib.parse

from backend.search_providers.types import normalize_result

_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_SOURCE = "Brave Search"


def _default_fetch(url: str, headers: dict | None = None) -> dict:
    import requests

    resp = requests.get(url, headers=headers or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def search(query: str, since: str | None = None, limit: int = 10, fetch=None) -> list[dict]:
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        return []
    fetch = fetch or _default_fetch
    params = {"q": query, "count": max(1, min(limit, 20))}
    url = f"{_ENDPOINT}?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    try:
        payload = fetch(url, headers=headers)
        results = ((payload or {}).get("web") or {}).get("results") or []
    except Exception as exc:
        print(f"[brave] recherche en erreur: {exc}")
        return []
    out: list[dict] = []
    for r in results[:limit]:
        raw = {
            "title": r.get("title"),
            "description": r.get("description"),
            "url": r.get("url"),
            "date": r.get("page_age") or r.get("age"),
        }
        if raw["url"]:
            out.append(normalize_result(raw, _SOURCE))
    return out
