"""Cache d'extraction IA (Cycle 2a).

extract_cached() consulte la table `extractions` et n'appelle l'IA que sur miss.
Issues mises en cache définitivement : 'closure', 'none'. Une issue 'error' est
ré-essayable (attempts + retry_after backoff), jamais bloquante pour toujours.
Clé : (content_hash, extraction_version, model).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import config
from backend import store


def content_hash(article: dict) -> str:
    payload = f"{article.get('titre', '')}\n{article.get('texte', '')}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _error_bloque(row: dict, now: datetime) -> bool:
    if (row.get("attempts") or 0) >= config.EXTRACTION_MAX_ATTEMPTS:
        return True
    retry_after = row.get("retry_after")
    if retry_after:
        try:
            return now < datetime.fromisoformat(retry_after)
        except ValueError:
            return False
    return False


def extract_cached_with_status(article, extract_fn, conn, *, model=None, version=None, now_fn=None):
    model = model or config.EXTRACTION_CACHE_MODEL
    version = config.EXTRACTION_VERSION if version is None else version
    now_fn = now_fn or _now
    chash = content_hash(article)

    row = store.get_extraction(conn, chash, version, model)
    if row:
        if row["status"] == "closure":
            return json.loads(row["result_json"]), "closure"
        if row["status"] == "none":
            return None, "none"
        if row["status"] == "error" and _error_bloque(row, now_fn()):
            return None, "error_skip"
        # status == 'error' non bloqué -> on retombe sur un nouvel essai

    now_iso = now_fn().isoformat()
    created_at = (row.get("created_at") if row else None) or now_iso
    try:
        result = extract_fn(article)
    except Exception as exc:
        attempts = ((row.get("attempts") if row else 0) or 0) + 1
        backoff = config.EXTRACTION_RETRY_BASE_MIN * (2 ** (attempts - 1))
        store.upsert_extraction(conn, {
            "content_hash": chash, "extraction_version": version, "model": model,
            "status": "error", "result_json": None, "error_type": type(exc).__name__,
            "attempts": attempts,
            "retry_after": (now_fn() + timedelta(minutes=backoff)).isoformat(),
            "created_at": created_at, "updated_at": now_iso,
        })
        return None, "error"

    store.upsert_extraction(conn, {
        "content_hash": chash, "extraction_version": version, "model": model,
        "status": "closure" if result is not None else "none",
        "result_json": json.dumps(result) if result is not None else None,
        "error_type": None, "attempts": (row.get("attempts") if row else 0) or 0,
        "retry_after": None, "created_at": created_at, "updated_at": now_iso,
    })
    return result, "closure" if result is not None else "none"


def extract_cached(article, extract_fn, conn, *, model=None, version=None, now_fn=None):
    result, _status = extract_cached_with_status(
        article, extract_fn, conn, model=model, version=version, now_fn=now_fn
    )
    return result
