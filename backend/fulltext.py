"""Récupération du fulltext + métadonnées, cache-first en SQLite.

API publique :
    fetch_article(url, fetch=None, conn=None) -> dict   (clés = store._ARTICLE_COLS)
    fetch_text(url, fetch=None, cache_dir=None, conn=None) -> str  (thin wrapper, compat)

Best-effort : aucune exception ne se propage ; un échec produit fetch_status='error'.
Cache-first : une URL déjà en base avec fetch_status='ok' n'est jamais refetchée.
Le `fetch` injectable peut renvoyer : FetchResult(text, url), un requests.Response
(.text/.url), un dict {"text","url"}, ou simplement une chaîne HTML.
"""
from __future__ import annotations

import hashlib
from collections import namedtuple
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
import trafilatura

import config
from backend import store

FetchResult = namedtuple("FetchResult", ["text", "url"])

_HEADERS = {"User-Agent": "veille-presse/1.0"}
_default_conn = None


def _get_default_conn():
    global _default_conn
    if _default_conn is None:
        _default_conn = store.init_db(config.DB_PATH)
    return _default_conn


def _default_fetch(url: str) -> FetchResult:
    resp = requests.get(url, timeout=10, headers=_HEADERS)
    resp.raise_for_status()
    return FetchResult(text=resp.text, url=resp.url)


def _hash16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_fetch(res, url: str) -> tuple[str, str]:
    """Normalise le retour d'un fetch en (html, final_url).

    Accepte : str HTML, dict {"text","url"}, ou tout objet exposant .text/.url
    (FetchResult, requests.Response).
    """
    if isinstance(res, str):
        return res, url
    if isinstance(res, dict):
        return res.get("text") or "", res.get("url") or url
    return (getattr(res, "text", "") or ""), (getattr(res, "url", None) or url)


def fetch_article(url: str, fetch=None, conn=None) -> dict:
    fetch = fetch or _default_fetch
    conn = conn or _get_default_conn()

    cached = store.get_article(conn, url)
    if cached and cached.get("fetch_status") == "ok":
        return cached

    fetched_at = _now_iso()
    try:
        html, final_url = _coerce_fetch(fetch(url), url)
    except Exception:
        row = {"raw_url": url, "final_url": None, "canonical_url": None, "title": None,
               "source_domain": None, "published_at": None, "fetched_at": fetched_at,
               "fulltext": "", "fulltext_hash": None, "fetch_status": "error"}
        store.upsert_article(conn, row)
        return row

    try:
        fulltext = trafilatura.extract(html) or ""
    except Exception:
        fulltext = ""

    title = published_at = canonical_url = None
    try:
        md = trafilatura.extract_metadata(html)
        if md is not None:
            title = md.title
            published_at = md.date
            canonical_url = md.url
    except Exception:
        pass

    row = {
        "raw_url": url,
        "final_url": final_url,
        "canonical_url": canonical_url,
        "title": title,
        "source_domain": urlparse(final_url).netloc or None,
        "published_at": published_at,
        "fetched_at": fetched_at,
        "fulltext": fulltext,
        "fulltext_hash": _hash16(fulltext) if fulltext else None,
        "fetch_status": "ok" if fulltext else "empty",
    }
    store.upsert_article(conn, row)
    return row


def fetch_text(url: str, fetch=None, cache_dir=None, conn=None) -> str:
    # cache_dir : accepté mais ignoré (déprécié, compat ascendante).
    return fetch_article(url, fetch=fetch, conn=conn).get("fulltext") or ""
