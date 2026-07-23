"""Collecteur Media Cloud, activé avec une clé de recherche gratuite."""
from __future__ import annotations

from datetime import date, timedelta

import config
from backend.collectors.news_queries import mediacloud_query


def _default_client(api_key: str):
    import mediacloud.api

    return mediacloud.api.SearchApi(api_key)


def parse_stories(stories: list[dict]) -> list[dict]:
    articles: list[dict] = []
    for story in stories:
        url = (story.get("url") or "").strip()
        if not url:
            continue
        publisher = story.get("media_name") or story.get("media_url")
        published = story.get("publish_date") or story.get("indexed_date") or ""
        if hasattr(published, "isoformat"):
            published = published.isoformat()
        articles.append({
            "titre": story.get("title") or "",
            # Media Cloud autorise la recherche plein texte mais ne redistribue
            # pas le corps. La pipeline enrichira l'URL chez l'éditeur.
            "texte": "",
            "url": url,
            "date": published,
            "source": publisher or "Media Cloud",
            "departement": None,
            "canal": "mediacloud",
        })
    return articles


def collect(
    client=None,
    api_key: str | None = None,
    since_date: str | None = None,
    end_date: str | None = None,
    max_pages: int | None = None,
    max_articles: int | None = None,
) -> list[dict]:
    if not config.MEDIACLOUD_ENABLED:
        return []
    key = config.MEDIACLOUD_API_KEY if api_key is None else api_key
    if client is None:
        if not key:
            print("[mediacloud] MEDIACLOUD_API_KEY absente - collecteur ignoré")
            return []
        try:
            client = _default_client(key)
        except Exception as exc:
            print(f"[mediacloud] client indisponible: {exc}")
            return []

    start = date.fromisoformat(
        since_date or (date.today() - timedelta(days=60)).isoformat()
    )
    end = date.fromisoformat(end_date or date.today().isoformat())
    page_limit = max(0, config.MEDIACLOUD_MAX_PAGES if max_pages is None else max_pages)
    article_limit = max(
        0, config.MEDIACLOUD_MAX_ARTICLES if max_articles is None else max_articles
    )
    if not page_limit or not article_limit:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    pagination_token = None
    for _ in range(page_limit):
        try:
            page, pagination_token = client.story_list(
                mediacloud_query(),
                start_date=start,
                end_date=end,
                pagination_token=pagination_token,
            )
        except Exception as exc:
            print(f"[mediacloud] recherche en erreur: {exc}")
            break
        for article in parse_stories(page or []):
            if article["url"] in seen:
                continue
            seen.add(article["url"])
            out.append(article)
            if len(out) >= article_limit:
                return out
        if not pagination_token:
            break
    return out
