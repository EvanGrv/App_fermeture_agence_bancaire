"""Registre des providers de recherche web.

Agrège les providers actifs (WEB_SEARCH_PROVIDERS), déduplique par URL et
capture les erreurs : un provider en panne n'empêche pas les autres.
"""
from __future__ import annotations

import os

from backend.search_providers import brave, bing, local_sitemap

# Nom -> fonction search(query, since=None, limit=10) -> list[dict]
PROVIDERS = {
    "brave": brave.search,
    "bing": bing.search,
    "local_sitemap": local_sitemap.search,
}

_DEFAULT = "brave,bing,local_sitemap"


def enabled_providers() -> list[str]:
    raw = os.environ.get("WEB_SEARCH_PROVIDERS", _DEFAULT)
    return [name.strip() for name in raw.split(",") if name.strip()]


def search(query: str, since: str | None = None, limit: int = 10) -> list[dict]:
    """Interroge tous les providers actifs et renvoie des articles dédupliqués."""
    seen: set[str] = set()
    out: list[dict] = []
    for name in enabled_providers():
        fn = PROVIDERS.get(name)
        if fn is None:
            continue
        try:
            results = fn(query, since=since, limit=limit) or []
        except Exception as exc:
            print(f"[search_providers] {name} en erreur: {exc}")
            continue
        for art in results:
            url = (art.get("url") or "").strip()
            if url and url in seen:
                continue
            if url:
                seen.add(url)
            out.append(art)
    return out
