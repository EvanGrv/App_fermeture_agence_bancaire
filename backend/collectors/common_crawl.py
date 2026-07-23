"""Backfill ciblé de presse française depuis les archives Common Crawl."""
from __future__ import annotations

import html as html_module
import json
import math
import re
from datetime import date, datetime
from io import BytesIO
from urllib.parse import urlparse

import requests
import trafilatura

import config
from backend import prefilter
from backend.collectors.news_queries import (
    COMMON_CRAWL_BANK_URL_FILTER,
    COMMON_CRAWL_CLOSURE_URL_FILTER,
)

_COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"
_INDEX_BASE = "https://index.commoncrawl.org"
_DATA_BASE = "https://data.commoncrawl.org"
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def is_deep_run(since_date: str | None, today: date | None = None) -> bool:
    if not config.COMMON_CRAWL_ENABLED or not since_date:
        return False
    try:
        start = date.fromisoformat(since_date)
    except ValueError:
        return False
    current = today or date.today()
    return (current - start).days >= config.COMMON_CRAWL_MIN_DAYS


def _parse_crawl_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        return None


def select_indexes(
    collections: list[dict],
    since_date: str,
    max_indexes: int,
    today: date | None = None,
) -> list[str]:
    start = date.fromisoformat(since_date)
    current = today or date.today()
    eligible = []
    for item in collections:
        crawl_date = _parse_crawl_date(item.get("to") or item.get("from"))
        if crawl_date and start <= crawl_date <= current and item.get("id"):
            eligible.append((crawl_date, item["id"]))
    eligible.sort(reverse=True)
    if max_indexes <= 0 or not eligible:
        return []
    if len(eligible) <= max_indexes:
        return [item_id for _, item_id in eligible]
    if max_indexes == 1:
        return [eligible[0][1]]
    # Échantillonne toute la fenêtre, au lieu de ne regarder que les crawls récents.
    positions = {
        round(i * (len(eligible) - 1) / (max_indexes - 1))
        for i in range(max_indexes)
    }
    return [eligible[pos][1] for pos in sorted(positions)]


def select_domains(
    domains: list[str],
    max_domains: int,
    today: date | None = None,
) -> list[str]:
    if max_domains <= 0 or not domains:
        return []
    if len(domains) <= max_domains:
        return domains[:]
    current = today or date.today()
    batches = math.ceil(len(domains) / max_domains)
    cycle = current.isocalendar().year * 53 + current.isocalendar().week
    start = (cycle % batches) * max_domains
    # Le dernier lot reboucle pour conserver une charge constante.
    return [domains[(start + i) % len(domains)] for i in range(max_domains)]


def _default_collinfo_fetch() -> list[dict]:
    response = requests.get(
        _COLLINFO_URL,
        timeout=config.COMMON_CRAWL_TIMEOUT,
        headers={"User-Agent": "veille-presse/1.0"},
    )
    response.raise_for_status()
    return response.json()


def _default_index_fetch(index_id: str, domain: str, limit: int) -> list[dict]:
    response = requests.get(
        f"{_INDEX_BASE}/{index_id}-index",
        params={
            "url": f"{domain}/*",
            "output": "json",
            "filter": [
                "=status:200",
                "=mime:text/html",
                f"~url:{COMMON_CRAWL_CLOSURE_URL_FILTER}",
                f"~url:{COMMON_CRAWL_BANK_URL_FILTER}",
            ],
            "collapse": "urlkey",
            "limit": str(limit),
        },
        timeout=config.COMMON_CRAWL_TIMEOUT,
        headers={"User-Agent": "veille-presse/1.0"},
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    records = []
    for line in response.text.splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _default_record_fetch(record: dict) -> bytes:
    offset = int(record["offset"])
    length = int(record["length"])
    if length <= 0 or length > config.COMMON_CRAWL_MAX_RECORD_BYTES:
        raise ValueError(f"taille WARC refusée: {length} octets")
    response = requests.get(
        f"{_DATA_BASE}/{record['filename']}",
        headers={
            "Range": f"bytes={offset}-{offset + length - 1}",
            "User-Agent": "veille-presse/1.0",
        },
        timeout=config.COMMON_CRAWL_TIMEOUT,
    )
    response.raise_for_status()
    return response.content


def extract_warc_payload(compressed_record: bytes) -> bytes:
    from warcio.archiveiterator import ArchiveIterator

    for record in ArchiveIterator(BytesIO(compressed_record)):
        if record.rec_type in {"response", "resource"}:
            return record.content_stream().read()
    return b""


def _title_from_html(raw_html: str) -> str:
    match = _TITLE_RE.search(raw_html)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    return html_module.unescape(title)


def record_to_article(record: dict, compressed_record: bytes) -> dict | None:
    payload = extract_warc_payload(compressed_record)
    if not payload:
        return None
    raw_html = payload.decode(record.get("encoding") or "utf-8", errors="replace")
    text = trafilatura.extract(
        raw_html,
        include_comments=False,
        include_tables=False,
    ) or ""
    article = {
        "titre": _title_from_html(raw_html),
        "texte": text[:20000],
        "url": record.get("url") or "",
        # Common Crawl connaît la date de capture, pas toujours la publication.
        "date": (record.get("timestamp") or "")[:8],
        "source": urlparse(record.get("url") or "").netloc or "Common Crawl",
        "departement": None,
        "canal": "common_crawl",
    }
    if len(article["date"]) == 8 and article["date"].isdigit():
        article["date"] = (
            f"{article['date'][:4]}-{article['date'][4:6]}-{article['date'][6:]}"
        )
    if not article["url"] or not prefilter.is_relevant(article):
        return None
    return article


def collect(
    since_date: str | None = None,
    today: date | None = None,
    domains: list[str] | None = None,
    collinfo_fetch=_default_collinfo_fetch,
    index_fetch=_default_index_fetch,
    record_fetch=_default_record_fetch,
    max_domains: int | None = None,
    max_indexes: int | None = None,
    records_per_domain: int | None = None,
    max_articles: int | None = None,
) -> list[dict]:
    current = today or date.today()
    if not is_deep_run(since_date, current):
        return []
    domain_limit = max(
        0, config.COMMON_CRAWL_MAX_DOMAINS if max_domains is None else max_domains
    )
    index_limit = max(
        0, config.COMMON_CRAWL_MAX_INDEXES if max_indexes is None else max_indexes
    )
    record_limit = max(
        0,
        config.COMMON_CRAWL_RECORDS_PER_DOMAIN
        if records_per_domain is None
        else records_per_domain,
    )
    article_limit = max(
        0, config.COMMON_CRAWL_MAX_ARTICLES if max_articles is None else max_articles
    )
    if not domain_limit or not index_limit or not record_limit or not article_limit:
        return []

    try:
        indexes = select_indexes(
            collinfo_fetch(), since_date, index_limit, current
        )
    except Exception as exc:
        print(f"[common_crawl] liste des index inaccessible: {exc}")
        return []
    selected_domains = select_domains(
        domains or config.COMMON_CRAWL_DOMAINS, domain_limit, current
    )
    if not indexes or not selected_domains:
        return []

    per_index = max(1, math.ceil(record_limit / len(indexes)))
    candidates: list[dict] = []
    seen_candidates: set[str] = set()
    for domain in selected_domains:
        domain_records = 0
        for index_id in indexes:
            try:
                records = index_fetch(index_id, domain, per_index)
            except Exception as exc:
                print(f"[common_crawl] index {index_id}/{domain} en erreur: {exc}")
                continue
            for record in records:
                url = (record.get("url") or "").strip()
                if not url or url in seen_candidates:
                    continue
                seen_candidates.add(url)
                candidates.append(record)
                domain_records += 1
                if domain_records >= record_limit:
                    break
            if domain_records >= record_limit:
                break

    articles: list[dict] = []
    for record in candidates:
        try:
            article = record_to_article(record, record_fetch(record))
        except Exception as exc:
            print(f"[common_crawl] capture ignorée ({record.get('url', '')}): {exc}")
            continue
        if article:
            articles.append(article)
            if len(articles) >= article_limit:
                break
    print(
        f"[common_crawl] {len(articles)} article(s) retenus depuis "
        f"{len(selected_domains)} domaine(s) et {len(indexes)} crawl(s)"
    )
    return articles
