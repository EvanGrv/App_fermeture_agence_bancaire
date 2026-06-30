# Cycle 2a — Fulltext + cache + cache d'extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Récupérer le fulltext de façon systématique mais cache-first, le stocker avec ses métadonnées en SQLite, et ne jamais relancer l'IA sur un contenu déjà extrait (même version, même modèle) — y compris les résultats `none` — sans jamais bloquer un article sur une erreur.

**Architecture:** Deux tables SQLite dans `press.db` (`articles`, `extractions`). `fulltext.py` refondu : `fetch_article(url)->dict` (cache-first, métadonnées, hash) + `fetch_text(url)->str` conservé comme thin wrapper. Un module `extraction_cache.py` enveloppe l'appel IA et consulte/écrit la table `extractions`. `run_pipeline` enrichit via fetch (systématique) et extrait via `extract_cached`.

**Tech Stack:** Python 3.12, sqlite3 (stdlib), trafilatura, requests, pytest.

## Global Constraints

- **Interpréteur : `python3.12`** uniquement (config.py exige 3.10+).
- **Stockage SQLite dans `press.db`** ; pas de nouvelle dépendance (JSON/CSV/sqlite).
- **Cache-first** : ne jamais refetch une URL déjà en base avec `fetch_status='ok'`.
- **Cacher `closure` et `none`** comme hits définitifs ; **jamais** `error`.
- **`error` ré-essayable** : colonnes `error_type`/`attempts`/`retry_after`, backoff.
- **Clé du cache d'extraction** : `PRIMARY KEY(content_hash, extraction_version, model)`.
- **Compat** : `fetch_text(url, ...) -> str` conservé pour les appelants production (qui n'appellent qu'avec l'URL) ; `cache_dir` retiré (sans objet sous SQLite) ; le `fetch` injectable renvoie désormais `FetchResult(text, url)`.
- **Pas de changement du schéma d'extraction IA** (réservé 2c).
- Constantes : `EXTRACTION_VERSION=1`, `EXTRACTION_MAX_ATTEMPTS=3`, `EXTRACTION_RETRY_BASE_MIN=60`.

---

## Structure des fichiers

- **Modify** `backend/store.py` : tables `articles` + `extractions` dans `_SCHEMA` + CRUD (`upsert_article`, `get_article`, `upsert_extraction`, `get_extraction`).
- **Modify** `backend/fulltext.py` : `FetchResult`, `fetch_article`, `fetch_text` (wrapper), conn par défaut paresseuse.
- **Create** `backend/extraction_cache.py` : `content_hash`, `extract_cached`.
- **Modify** `config.py` : 3 constantes d'extraction.
- **Modify** `backend/pipeline.py` : enrich systématique via `fetch_article`, extraction via `extract_cached`.
- **Modify tests** : `tests/test_store.py` (+tables), `tests/test_fulltext.py` (nouveau contrat), `tests/test_pipeline.py` (`test_article_long_*` repurposé), **Create** `tests/test_extraction_cache.py`.

---

### Task 1: Tables SQLite `articles` + `extractions` et CRUD

**Files:**
- Modify: `backend/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces:
  - `upsert_article(conn, article: dict) -> None` (clé `raw_url`).
  - `get_article(conn, raw_url: str) -> dict | None`.
  - `upsert_extraction(conn, row: dict) -> None` (clé `content_hash, extraction_version, model`).
  - `get_extraction(conn, content_hash: str, extraction_version: int, model: str) -> dict | None`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_store.py (ajouter en bas)
def test_init_db_cree_tables_articles_extractions(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    noms = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "articles" in noms
    assert "extractions" in noms


def test_upsert_get_article_round_trip(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    art = {"raw_url": "http://a", "final_url": "http://a/final", "canonical_url": None,
           "title": "T", "source_domain": "a", "published_at": "2026-06-25",
           "fetched_at": "2026-06-30T00:00:00+00:00", "fulltext": "corps",
           "fulltext_hash": "deadbeef", "fetch_status": "ok"}
    store.upsert_article(conn, art)
    got = store.get_article(conn, "http://a")
    assert got["fulltext"] == "corps"
    assert got["fetch_status"] == "ok"
    assert got["final_url"] == "http://a/final"
    # upsert idempotent : second appel met à jour sans dupliquer
    art["fetch_status"] = "empty"
    store.upsert_article(conn, art)
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
    assert store.get_article(conn, "http://a")["fetch_status"] == "empty"
    assert store.get_article(conn, "http://absent") is None


def test_upsert_get_extraction_round_trip(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    row = {"content_hash": "h1", "extraction_version": 1, "model": "claude-haiku-4-5",
           "status": "none", "result_json": None, "error_type": None,
           "attempts": 0, "retry_after": None,
           "created_at": "2026-06-30T00:00:00+00:00", "updated_at": "2026-06-30T00:00:00+00:00"}
    store.upsert_extraction(conn, row)
    got = store.get_extraction(conn, "h1", 1, "claude-haiku-4-5")
    assert got["status"] == "none"
    # même contenu/version mais modèle différent -> clé distincte
    assert store.get_extraction(conn, "h1", 1, "claude-sonnet-4-6") is None
    # upsert sur la même clé met à jour
    row["status"] = "closure"; row["result_json"] = "{}"
    store.upsert_extraction(conn, row)
    assert conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0] == 1
    assert store.get_extraction(conn, "h1", 1, "claude-haiku-4-5")["status"] == "closure"
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_store.py -k "articles or extraction" -v`
Expected: FAIL (`AttributeError: module 'backend.store' has no attribute 'upsert_article'`).

- [ ] **Step 3: Implémenter**

```python
# backend/store.py — ajouter dans la chaîne _SCHEMA (avant la triple-quote fermante)
CREATE TABLE IF NOT EXISTS articles (
    raw_url        TEXT PRIMARY KEY,
    final_url      TEXT,
    canonical_url  TEXT,
    title          TEXT,
    source_domain  TEXT,
    published_at   TEXT,
    fetched_at     TEXT NOT NULL,
    fulltext       TEXT,
    fulltext_hash  TEXT,
    fetch_status   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extractions (
    content_hash       TEXT NOT NULL,
    extraction_version INTEGER NOT NULL,
    model              TEXT NOT NULL,
    status             TEXT NOT NULL,
    result_json        TEXT,
    error_type         TEXT,
    attempts           INTEGER NOT NULL DEFAULT 0,
    retry_after        TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    PRIMARY KEY (content_hash, extraction_version, model)
);
```

```python
# backend/store.py — ajouter ces fonctions et constantes de colonnes
_ARTICLE_COLS = ["raw_url", "final_url", "canonical_url", "title", "source_domain",
                 "published_at", "fetched_at", "fulltext", "fulltext_hash", "fetch_status"]
_EXTRACTION_COLS = ["content_hash", "extraction_version", "model", "status",
                    "result_json", "error_type", "attempts", "retry_after",
                    "created_at", "updated_at"]


def upsert_article(conn, article: dict) -> None:
    cols = ",".join(_ARTICLE_COLS)
    placeholders = ",".join(f":{c}" for c in _ARTICLE_COLS)
    updates = ",".join(f"{c}=excluded.{c}" for c in _ARTICLE_COLS if c != "raw_url")
    conn.execute(
        f"INSERT INTO articles ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(raw_url) DO UPDATE SET {updates}",
        {c: article.get(c) for c in _ARTICLE_COLS},
    )
    conn.commit()


def get_article(conn, raw_url: str) -> dict | None:
    row = conn.execute(
        f"SELECT {','.join(_ARTICLE_COLS)} FROM articles WHERE raw_url=?", (raw_url,)
    ).fetchone()
    return dict(zip(_ARTICLE_COLS, row)) if row else None


def upsert_extraction(conn, row: dict) -> None:
    cols = ",".join(_EXTRACTION_COLS)
    placeholders = ",".join(f":{c}" for c in _EXTRACTION_COLS)
    key = ("content_hash", "extraction_version", "model")
    updates = ",".join(f"{c}=excluded.{c}" for c in _EXTRACTION_COLS if c not in key)
    conn.execute(
        f"INSERT INTO extractions ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(content_hash, extraction_version, model) DO UPDATE SET {updates}",
        {c: row.get(c) for c in _EXTRACTION_COLS},
    )
    conn.commit()


def get_extraction(conn, content_hash: str, extraction_version: int, model: str) -> dict | None:
    row = conn.execute(
        f"SELECT {','.join(_EXTRACTION_COLS)} FROM extractions "
        "WHERE content_hash=? AND extraction_version=? AND model=?",
        (content_hash, extraction_version, model),
    ).fetchone()
    return dict(zip(_EXTRACTION_COLS, row)) if row else None
```

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_store.py -v`
Expected: PASS (anciens + nouveaux).

- [ ] **Step 5: Commit**

```bash
git add backend/store.py tests/test_store.py
git commit -m "feat(2a): tables SQLite articles + extractions + CRUD"
```

---

### Task 2: Refonte `fulltext.py` (cache-first + métadonnées)

**Files:**
- Modify: `backend/fulltext.py`
- Test: `tests/test_fulltext.py` (réécrire le contrat)

**Interfaces:**
- Consumes: `store.get_article`, `store.upsert_article`, `store.init_db`, `config.DB_PATH`.
- Produces:
  - `FetchResult = namedtuple("FetchResult", ["text", "url"])`.
  - `fetch_article(url, fetch=None, conn=None) -> dict` (clés = `_ARTICLE_COLS`).
  - `fetch_text(url, fetch=None, conn=None) -> str`.

- [ ] **Step 1: Réécrire le test (nouveau contrat)**

```python
# tests/test_fulltext.py — REMPLACER tout le fichier
"""Tests pour backend/fulltext.py — fetch_article (SQLite, cache-first) + fetch_text."""
import backend.store as store
from backend.fulltext import FetchResult, fetch_article, fetch_text

_ARTICLE_HTML = """\
<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<title>Fermeture agence Crédit Agricole à Limoges</title></head>
<body><main><article>
<h1>Le Crédit Agricole ferme son agence du centre-ville de Limoges</h1>
<p>Le Crédit Agricole Centre Ouest a annoncé la fermeture définitive de son agence
rue Jean-Jaurès à Limoges, prévue pour le 30 septembre 2026. Cette décision s'inscrit
dans le plan de rationalisation du réseau bancaire régional, qui vise à concentrer les
services sur des agences plus grandes et mieux équipées pour la clientèle locale.</p>
<p>Selon le directeur régional, les clients seront redirigés vers l'agence de la place
Denis-Dussoubs, distante de seulement 400 mètres, avec des conseillers dédiés.</p>
</article></main></body></html>
"""


def _fetch_ok(url):
    return FetchResult(text=_ARTICLE_HTML, url=url)


def test_fetch_article_upsert_avec_hash_et_metadonnees(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    row = fetch_article("https://ex.com/a", fetch=_fetch_ok, conn=conn)
    assert row["fetch_status"] == "ok"
    assert "Crédit Agricole" in row["fulltext"]
    assert row["fulltext_hash"] and len(row["fulltext_hash"]) == 16
    assert row["source_domain"] == "ex.com"
    # persistée
    assert store.get_article(conn, "https://ex.com/a")["fetch_status"] == "ok"


def test_fetch_article_cache_first_ne_refetch_pas(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    appels = []

    def fetch_spy(url):
        appels.append(url)
        return FetchResult(text=_ARTICLE_HTML, url=url)

    fetch_article("https://ex.com/cache", fetch=fetch_spy, conn=conn)
    fetch_article("https://ex.com/cache", fetch=fetch_spy, conn=conn)
    assert len(appels) == 1, f"fetch appelé {len(appels)} fois au lieu de 1"


def test_fetch_text_renvoie_le_corps(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    txt = fetch_text("https://ex.com/t", fetch=_fetch_ok, conn=conn)
    assert isinstance(txt, str) and "Crédit Agricole" in txt


def test_fetch_article_echec_status_error_refetchable(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    appels = []

    def fetch_raises(url):
        appels.append(url)
        raise RuntimeError("Connexion refusée")

    row = fetch_article("https://ex.com/ko", fetch=fetch_raises, conn=conn)
    assert row["fetch_status"] == "error"
    assert row["fulltext"] == ""
    # cache-first ne court-circuite QUE 'ok' -> un 2e appel re-tente le fetch
    fetch_article("https://ex.com/ko", fetch=fetch_raises, conn=conn)
    assert len(appels) == 2
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_fulltext.py -v`
Expected: FAIL (`ImportError: cannot import name 'FetchResult'` / `fetch_article`).

- [ ] **Step 3: Implémenter (réécriture du module)**

```python
# backend/fulltext.py — REMPLACER tout le fichier
"""Récupération du fulltext + métadonnées, cache-first en SQLite.

API publique :
    fetch_article(url, fetch=None, conn=None) -> dict   (clés = store._ARTICLE_COLS)
    fetch_text(url, fetch=None, conn=None) -> str        (thin wrapper, compat)

Best-effort : aucune exception ne se propage ; un échec produit fetch_status='error'.
Cache-first : une URL déjà en base avec fetch_status='ok' n'est jamais refetchée.
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


def fetch_article(url: str, fetch=None, conn=None) -> dict:
    fetch = fetch or _default_fetch
    conn = conn or _get_default_conn()

    cached = store.get_article(conn, url)
    if cached and cached.get("fetch_status") == "ok":
        return cached

    fetched_at = _now_iso()
    try:
        res = fetch(url)
        html = res.text
        final_url = res.url or url
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


def fetch_text(url: str, fetch=None, conn=None) -> str:
    return fetch_article(url, fetch=fetch, conn=conn).get("fulltext") or ""
```

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_fulltext.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/fulltext.py tests/test_fulltext.py
git commit -m "feat(2a): fulltext cache-first SQLite + métadonnées (fetch_article)"
```

---

### Task 3: Module `extraction_cache.py` + constantes config

**Files:**
- Modify: `config.py`
- Create: `backend/extraction_cache.py`
- Test: `tests/test_extraction_cache.py`

**Interfaces:**
- Consumes: `store.get_extraction`, `store.upsert_extraction`, `config.ANTHROPIC_MODEL`, `config.EXTRACTION_VERSION`, `config.EXTRACTION_MAX_ATTEMPTS`, `config.EXTRACTION_RETRY_BASE_MIN`.
- Produces:
  - `content_hash(article: dict) -> str` (SHA-256[:16] de `titre\ntexte`).
  - `extract_cached(article, extract_fn, conn, *, model=None, version=None, now_fn=None) -> dict | None`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_extraction_cache.py
from datetime import datetime, timedelta, timezone

import backend.store as store
import config
from backend.extraction_cache import content_hash, extract_cached

_ART = {"titre": "BNP ferme", "texte": "agence fermée à Lyon"}


def _conn(tmp_path):
    return store.init_db(tmp_path / "t.db")


def test_miss_appelle_extract_et_cache_closure(tmp_path):
    conn = _conn(tmp_path)
    appels = []

    def extract_fn(art):
        appels.append(1)
        return {"id": "x", "banque": "BNP"}

    r = extract_cached(_ART, extract_fn, conn)
    assert r == {"id": "x", "banque": "BNP"}
    assert len(appels) == 1
    # 2e appel -> HIT, pas de rappel
    r2 = extract_cached(_ART, extract_fn, conn)
    assert r2 == {"id": "x", "banque": "BNP"}
    assert len(appels) == 1


def test_none_est_mis_en_cache(tmp_path):
    conn = _conn(tmp_path)
    appels = []

    def extract_fn(art):
        appels.append(1)
        return None

    assert extract_cached(_ART, extract_fn, conn) is None
    assert extract_cached(_ART, extract_fn, conn) is None
    assert len(appels) == 1, "none doit être caché : pas de second appel IA"


def test_cle_inclut_le_modele(tmp_path):
    conn = _conn(tmp_path)
    appels = []

    def extract_fn(art):
        appels.append(1)
        return None

    extract_cached(_ART, extract_fn, conn, model="claude-haiku-4-5")
    extract_cached(_ART, extract_fn, conn, model="claude-sonnet-4-6")
    assert len(appels) == 2, "modèle différent -> miss"


def test_cle_inclut_la_version(tmp_path):
    conn = _conn(tmp_path)
    appels = []

    def extract_fn(art):
        appels.append(1)
        return None

    extract_cached(_ART, extract_fn, conn, version=1)
    extract_cached(_ART, extract_fn, conn, version=2)
    assert len(appels) == 2


def test_error_reessayable_apres_retry_after(tmp_path):
    conn = _conn(tmp_path)
    appels = []
    t0 = datetime(2026, 6, 30, tzinfo=timezone.utc)

    def extract_boom(art):
        appels.append(1)
        raise RuntimeError("API 529")

    # 1er appel : échec -> status error, attempts=1, retry_after futur
    assert extract_cached(_ART, extract_boom, conn, now_fn=lambda: t0) is None
    assert len(appels) == 1
    row = store.get_extraction(conn, content_hash(_ART), config.EXTRACTION_VERSION,
                               config.ANTHROPIC_MODEL)
    assert row["status"] == "error" and row["attempts"] == 1 and row["retry_after"]
    # avant retry_after -> soft-skip (pas de rappel IA)
    assert extract_cached(_ART, extract_boom, conn, now_fn=lambda: t0) is None
    assert len(appels) == 1
    # après retry_after -> nouvel essai
    plus_tard = t0 + timedelta(minutes=config.EXTRACTION_RETRY_BASE_MIN + 1)
    assert extract_cached(_ART, extract_boom, conn, now_fn=lambda: plus_tard) is None
    assert len(appels) == 2


def test_error_bloque_apres_max_attempts(tmp_path):
    conn = _conn(tmp_path)
    futur = datetime(2030, 1, 1, tzinfo=timezone.utc)
    store.upsert_extraction(conn, {
        "content_hash": content_hash(_ART), "extraction_version": config.EXTRACTION_VERSION,
        "model": config.ANTHROPIC_MODEL, "status": "error", "result_json": None,
        "error_type": "X", "attempts": config.EXTRACTION_MAX_ATTEMPTS, "retry_after": None,
        "created_at": "2026-06-30T00:00:00+00:00", "updated_at": "2026-06-30T00:00:00+00:00"})
    appels = []

    def extract_fn(art):
        appels.append(1)
        return None

    assert extract_cached(_ART, extract_fn, conn, now_fn=lambda: futur) is None
    assert len(appels) == 0, "max_attempts atteint -> soft-skip même retry_after passé"
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_extraction_cache.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.extraction_cache`).

- [ ] **Step 3: Implémenter — config puis module**

```python
# config.py — ajouter après le bloc ANTHROPIC_FALLBACK_ENABLED (ligne ~18)
# Cache d'extraction IA (Cycle 2a) : ne jamais relancer l'IA sur un contenu déjà
# extrait pour (content_hash, extraction_version, model). Bump EXTRACTION_VERSION
# quand le prompt ou le schéma d'extraction change (invalidation propre).
EXTRACTION_VERSION = int(os.getenv("EXTRACTION_VERSION", "1"))
EXTRACTION_MAX_ATTEMPTS = int(os.getenv("EXTRACTION_MAX_ATTEMPTS", "3"))
EXTRACTION_RETRY_BASE_MIN = int(os.getenv("EXTRACTION_RETRY_BASE_MIN", "60"))
```

```python
# backend/extraction_cache.py — créer
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


def extract_cached(article, extract_fn, conn, *, model=None, version=None, now_fn=None):
    model = model or config.ANTHROPIC_MODEL
    version = config.EXTRACTION_VERSION if version is None else version
    now_fn = now_fn or _now
    chash = content_hash(article)

    row = store.get_extraction(conn, chash, version, model)
    if row:
        if row["status"] == "closure":
            return json.loads(row["result_json"])
        if row["status"] == "none":
            return None
        if row["status"] == "error" and _error_bloque(row, now_fn()):
            return None
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
        return None

    store.upsert_extraction(conn, {
        "content_hash": chash, "extraction_version": version, "model": model,
        "status": "closure" if result is not None else "none",
        "result_json": json.dumps(result) if result is not None else None,
        "error_type": None, "attempts": (row.get("attempts") if row else 0) or 0,
        "retry_after": None, "created_at": created_at, "updated_at": now_iso,
    })
    return result
```

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_extraction_cache.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add config.py backend/extraction_cache.py tests/test_extraction_cache.py
git commit -m "feat(2a): cache d'extraction IA (clé hash+version+model, none caché, error réessayable)"
```

---

### Task 4: Câblage dans `run_pipeline` (fulltext systématique + extraction cachée)

**Files:**
- Modify: `backend/pipeline.py`
- Test: `tests/test_pipeline.py` (repurposer `test_article_long_n_est_pas_enrichi`)

**Interfaces:**
- Consumes: `fulltext.fetch_article`, `extraction_cache.extract_cached`.
- Le comportement public de `run_pipeline(conn, collectors, extractor_fn, geocoder_fn, vigilance_fn, enrich_fn, since_date, progress_fn)` est inchangé sauf : enrichissement **systématique** (plus de seuil 400) et extraction via le cache.

- [ ] **Step 1: Mettre à jour / écrire les tests**

```python
# tests/test_pipeline.py — REMPLACER test_article_long_n_est_pas_enrichi par :
def test_fulltext_systematique_enrichit_meme_les_articles_longs(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    texte_long = "Crédit Agricole ferme son agence. " * 15  # > 400 chars
    article_long = {
        "titre": "Crédit Agricole ferme son agence", "texte": texte_long,
        "url": "http://exemple.com/article-long", "date": "2026-01-10",
        "source": "GN", "departement": None,
    }
    enrich_appels = []

    def enrich_espion(url):
        enrich_appels.append(url)
        return "texte additionnel"

    pipeline.run_pipeline(
        conn, [lambda: [article_long]],
        extractor_fn=lambda art: None,
        geocoder_fn=lambda commune, dept: None,
        enrich_fn=enrich_espion, since_date=None,
    )
    assert len(enrich_appels) == 1, "fulltext systématique : l'article long est aussi enrichi"


def test_pipeline_extraction_cachee_pas_de_2e_appel_ia(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    appels = []

    def extractor_compteur(art):
        appels.append(art["url"])
        return None  # 'none' doit être caché

    collectors = [lambda: [_article("http://cache-ia")]]
    pipeline.run_pipeline(conn, collectors, extractor_compteur, _geo,
                          enrich_fn=lambda u: "")
    # On efface seen_urls pour forcer le 2e passage jusqu'à l'extraction
    conn.execute("DELETE FROM seen_urls"); conn.commit()
    pipeline.run_pipeline(conn, collectors, extractor_compteur, _geo,
                          enrich_fn=lambda u: "")
    assert len(appels) == 1, "le cache d'extraction évite le 2e appel IA"
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_pipeline.py -k "systematique or cachee" -v`
Expected: FAIL (`test_fulltext_systematique...` : enrich non appelé car gate encore présent ; `test_pipeline_extraction_cachee...` : 2 appels car pas de cache).

- [ ] **Step 3: Implémenter le câblage**

Modifier les imports en tête de `backend/pipeline.py` :

```python
from backend import commune_normalize, prefilter, store, validation
from backend.fulltext import fetch_text, fetch_article
from backend.extraction_cache import extract_cached
```

Remplacer le bloc d'enrichissement (actuellement lignes ~108-116) par :

```python
            _enrich = enrich_fn if enrich_fn is not None else (
                lambda u: fetch_article(u, conn=conn).get("fulltext") or "")
            texte = art.get("texte") or ""
            if url:
                try:
                    texte_complet = _enrich(url)
                    if texte_complet:
                        art["texte"] = (texte + "\n\n" + texte_complet)[:6000]
                except Exception:
                    pass
```

Remplacer l'appel d'extraction (actuellement `resultat = extractor_fn(art)`) par :

```python
            try:
                resultat = extract_cached(art, extractor_fn, conn)
            except Exception as exc:
                print(f"[pipeline] extraction en erreur ({url}): {exc}")
                continue
```

- [ ] **Step 4: Lancer pour vérifier le succès (fichier puis suite complète)**

Run: `python3.12 -m pytest tests/test_pipeline.py -v`
Expected: PASS (tous, y compris `test_pipeline_idempotent`, `test_article_court_est_enrichi_avant_extraction`).

Run: `python3.12 -m pytest -q`
Expected: PASS (aucune régression sur les ~345 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline.py tests/test_pipeline.py
git commit -m "feat(2a): câblage pipeline — fulltext systématique cache-first + extraction cachée"
```

---

## Self-Review (effectuée)

- **Couverture du spec** : tables `articles`+`extractions` (Task 1) ; fulltext cache-first + métadonnées + `fetch_text` compat (Task 2) ; cache d'extraction `closure`/`none` + `error` réessayable + clé `(content_hash, version, model)` (Task 3) ; fulltext systématique + câblage (Task 4). Constantes config (Task 3). Critère « 2e run = 0 IA » couvert par `test_pipeline_extraction_cachee...` et les tests d'`extract_cached`.
- **Placeholders** : aucun ; code complet à chaque step.
- **Cohérence des types** : `_ARTICLE_COLS`/`_EXTRACTION_COLS` (store) alignés avec les dicts produits par `fetch_article` et `extract_cached` ; `get_extraction(conn, content_hash, extraction_version, model)` même signature partout ; `FetchResult(text, url)` consommé par `fetch_article`.
- **Changement de comportement assumé** : `test_article_long_n_est_pas_enrichi` est remplacé (le gate `<400` est retiré au profit du fulltext systématique) — documenté dans Task 4.
- **Note** : sur le run réel, le 1er passage refetch tout (capture fulltext+métadonnées) ; les passages suivants sont cache-first (articles `ok`) et 0 IA (extractions `none`/`closure`).
