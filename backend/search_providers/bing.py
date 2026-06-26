"""Provider Bing Search (Phase 6.2) — complément optionnel de Brave.

Clé via BING_SEARCH_API_KEY. Sans clé -> []. Toute erreur -> [].
Le pipeline ne doit jamais dépendre de Bing.
"""
from __future__ import annotations

import os
import urllib.parse

from backend.search_providers.types import normalize_result

_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
_SOURCE = "Bing Search"


def _default_fetch(url: str, headers: dict | None = None) -> dict:
    import requests

    resp = requests.get(url, headers=headers or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def search(query: str, since: str | None = None, limit: int = 10, fetch=None) -> list[dict]:
    api_key = os.environ.get("BING_SEARCH_API_KEY", "").strip()
    if not api_key:
        return []
    fetch = fetch or _default_fetch
    params = {"q": query, "count": max(1, min(limit, 50)), "mkt": "fr-FR"}
    url = f"{_ENDPOINT}?{urllib.parse.urlencode(params)}"
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    try:
        payload = fetch(url, headers=headers)
        results = ((payload or {}).get("webPages") or {}).get("value") or []
    except Exception as exc:
        print(f"[bing] recherche en erreur: {exc}")
        return []
    out: list[dict] = []
    for r in results[:limit]:
        raw = {
            "title": r.get("name"),
            "snippet": r.get("snippet"),
            "url": r.get("url"),
            "date": r.get("dateLastCrawled"),
        }
        if raw["url"]:
            out.append(normalize_result(raw, _SOURCE))
    return out
