"""Découverte web ciblée des projets de fermeture de bureaux de poste."""
from __future__ import annotations

import config

QUERIES = [
    '"fermeture définitive du bureau de poste"',
    '"bureau de poste" "fermeture prévue"',
    '"bureau de poste" "va fermer"',
    'site:politique.pappers.fr/commune/document "fermeture du bureau de poste"',
    'site:politique.pappers.fr/commune/document "agence postale communale" "fermeture"',
    '"bureau de poste" "fermera" 2026 OR 2027',
    '"transformation en agence postale communale" "bureau de poste"',
    '"création d\'un relais poste" "fermeture"',
    '"La Poste a informé la commune" fermeture bureau',
    '"conseil municipal" "fermeture du bureau de poste"',
    'site:cgt-fapt.fr "fermeture" "bureau de poste"',
    'site:sudptt.org "fermeture" "bureau de poste"',
]


def collect(search_fn=None, queries: list[str] | None = None, news_fn=None) -> list[dict]:
    if not config.POSTAL_WEB_ENABLED:
        return []
    if search_fn is None:
        from backend.search_providers import registry
        search_fn = registry.search
    if news_fn is None:
        from backend.collectors import google_news
        news_fn = google_news.collect
    selected = (queries or QUERIES)[:max(0, config.POSTAL_WEB_MAX_QUERIES)]
    seen: set[str] = set()
    out: list[dict] = []

    # Google News RSS constitue le canal sans clé. Il est particulièrement utile
    # pour les reprises presse de conseils municipaux et de conversions postales.
    try:
        news_results = news_fn(queries=selected) or []
    except Exception as exc:
        print(f"[postal_web] Google News en erreur: {exc}")
        news_results = []
    _append_results(out, seen, news_results)

    for query in selected:
        try:
            results = search_fn(query, limit=20) or []
        except Exception as exc:
            print(f"[postal_web] recherche en erreur ({query}): {exc}")
            continue
        _append_results(out, seen, results)
    return out


def _append_results(out: list[dict], seen: set[str], results: list[dict]) -> None:
    for article in results:
        url = (article.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({
            "titre": article.get("titre") or article.get("title") or "",
            "texte": article.get("texte") or article.get("extrait") or "",
            "url": url,
            "date": article.get("date"),
            "source": article.get("source") or "Recherche web postale",
            "departement": article.get("departement"),
            "canal": "postal_web",
        })
