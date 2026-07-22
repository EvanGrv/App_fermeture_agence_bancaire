"""Collecteur Event Registry / NewsAPI.ai à quota gratuit limité."""
from __future__ import annotations

from datetime import date, timedelta

import requests

import config
from backend.collectors.news_queries import event_registry_query

_ENDPOINT = "https://eventregistry.org/api/v1/article/getArticles"


def parse_response(payload: dict) -> list[dict]:
    results = (payload.get("articles") or {}).get("results") or []
    articles: list[dict] = []
    for item in results:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        source = item.get("source") or {}
        if isinstance(source, dict):
            publisher = source.get("title") or source.get("uri")
        else:
            publisher = str(source)
        articles.append({
            "titre": item.get("title") or "",
            "texte": item.get("body") or "",
            "url": url,
            "date": item.get("dateTimePub") or item.get("date") or "",
            "source": publisher or "Event Registry",
            "departement": None,
            "canal": "event_registry",
        })
    return articles


def _default_fetch(payload: dict) -> dict:
    response = requests.post(
        _ENDPOINT,
        json=payload,
        timeout=30,
        headers={"User-Agent": "veille-presse/1.0"},
    )
    response.raise_for_status()
    return response.json()


def _request_payload(
    api_key: str,
    since_date: str,
    end_date: str,
    page: int,
    count: int,
) -> dict:
    query = event_registry_query()
    query["$query"]["$and"].insert(0, {
        "dateStart": since_date,
        "dateEnd": end_date,
    })
    return {
        "action": "getArticles",
        "query": query,
        "dateStart": since_date,
        "dateEnd": end_date,
        "lang": "fra",
        "dataType": ["news", "blog"],
        "isDuplicateFilter": "skipDuplicates",
        "articlesPage": page,
        "articlesCount": count,
        "articlesSortBy": "date",
        "articlesSortByAsc": False,
        "articlesArticleBodyLen": -1,
        "resultType": "articles",
        "apiKey": api_key,
    }


def collect(
    fetch=_default_fetch,
    api_key: str | None = None,
    since_date: str | None = None,
    end_date: str | None = None,
    max_pages: int | None = None,
    max_articles: int | None = None,
) -> list[dict]:
    if not config.EVENT_REGISTRY_ENABLED:
        return []
    key = config.EVENT_REGISTRY_API_KEY if api_key is None else api_key
    if not key:
        print("[event_registry] EVENT_REGISTRY_API_KEY absente - collecteur ignoré")
        return []

    start = since_date or (date.today() - timedelta(days=60)).isoformat()
    end = end_date or date.today().isoformat()
    page_limit = max(
        0, config.EVENT_REGISTRY_MAX_PAGES if max_pages is None else max_pages
    )
    article_limit = max(
        0,
        config.EVENT_REGISTRY_MAX_ARTICLES
        if max_articles is None
        else max_articles,
    )
    if not page_limit or not article_limit:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for page_number in range(1, page_limit + 1):
        count = min(100, article_limit - len(out))
        if count <= 0:
            break
        try:
            payload = fetch(
                _request_payload(key, start, end, page_number, count)
            )
        except Exception as exc:
            print(f"[event_registry] recherche en erreur: {exc}")
            break
        if payload.get("error"):
            print(f"[event_registry] API indisponible/quota épuisé: {payload['error']}")
            break
        page = parse_response(payload)
        for article in page:
            if article["url"] in seen:
                continue
            seen.add(article["url"])
            out.append(article)
            if len(out) >= article_limit:
                return out
        pages = (payload.get("articles") or {}).get("pages")
        if not page or (isinstance(pages, int) and page_number >= pages):
            break
    return out
