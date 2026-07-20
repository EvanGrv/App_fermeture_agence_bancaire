"""Backfill profond des fermetures de bureaux bancaires La Banque Postale."""
from __future__ import annotations

from datetime import date

import config
from backend.collectors import google_news

THEMATIC_QUERIES = [
    '"fermeture définitive" "bureau de poste"',
    '"bureau de poste" "définitivement fermé"',
    '"bureau de poste" "transformé en agence postale communale"',
    '"bureau de poste" "transformation en agence postale communale"',
    '"bureau de poste" "devient une agence postale communale"',
    '"bureau de poste" "remplacé par une agence postale communale"',
    '"bureau de poste" "transformé en relais poste"',
    '"bureau de poste" "remplacé par un relais poste"',
    '"bureau de poste" "dernier jour d’ouverture"',
    '"bureau de poste" "suppression des services financiers"',
    '"bureau de poste" "suppression du service bancaire"',
    '"bureau de poste" "conseiller bancaire" fermeture',
]

DEPARTMENT_QUERIES = [
    f'("agence postale communale" OR "relais poste") "bureau de poste" {name}'
    for name in config.DEPARTEMENTS.values()
]

WEB_QUERIES = [
    'site:politique.pappers.fr/commune/document "bureau de poste" fermeture',
    'site:politique.pappers.fr/commune/document "agence postale communale"',
    'site:politique.pappers.fr/commune/document "relais poste"',
    'site:*.fr "délibération" "fermeture du bureau de poste"',
    'site:*.fr "conseil municipal" "agence postale communale"',
    'site:cgt-fapt.fr "fermeture" "bureau de poste"',
    'site:cgt-fapt.fr "transformation" "agence postale communale"',
    'site:sudptt.org "fermeture" "bureau de poste"',
    'site:sudptt.org "relais poste"',
    '"CDPPT" "fermeture" "bureau de poste"',
    '"commission départementale de présence postale" fermeture',
    '"La Poste a informé la commune" "fermeture"',
]


def _lookback_days() -> int | None:
    today = date.today()
    start = google_news._parse_when_to_start(
        getattr(config, "GOOGLE_NEWS_WHEN", ""), today
    )
    return (today - start).days if start else None


def is_deep_run() -> bool:
    days = _lookback_days()
    return bool(
        config.POSTAL_HISTORY_ENABLED
        and days is not None
        and days >= config.POSTAL_HISTORY_MIN_DAYS
    )


def collect(news_fn=None, search_fn=None) -> list[dict]:
    if not is_deep_run():
        return []
    news_fn = news_fn or google_news.collect
    if search_fn is None:
        from backend.search_providers import registry
        search_fn = registry.search

    results: list[dict] = []
    results.extend(news_fn(
        queries=THEMATIC_QUERIES, slice_queries=set(THEMATIC_QUERIES)
    ) or [])
    results.extend(news_fn(queries=DEPARTMENT_QUERIES) or [])
    for query in WEB_QUERIES[:max(0, config.POSTAL_HISTORY_WEB_MAX_QUERIES)]:
        try:
            results.extend(search_fn(query, limit=20) or [])
        except Exception as exc:
            print(f"[postal_history] recherche en erreur ({query}): {exc}")

    seen: set[str] = set()
    articles: list[dict] = []
    for article in results:
        url = (article.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        articles.append({
            "titre": article.get("titre") or article.get("title") or "",
            "texte": article.get("texte") or article.get("extrait") or "",
            "url": url,
            "date": article.get("date"),
            "source": article.get("source") or "Backfill postal historique",
            "departement": article.get("departement"),
            "canal": "postal_history",
        })
    print(
        f"[postal_history] {len(articles)} URL(s) uniques découvertes "
        f"sur {len(THEMATIC_QUERIES)} thèmes et {len(DEPARTMENT_QUERIES)} départements"
    )
    return articles
