# Cycle 2a — Fulltext systématique + cache + cache d'extraction (Design)

Date : 2026-06-30
Statut : approuvé sur le principe (ajustements intégrés). Spec détaillé d'un sous-cycle.

## Contexte

Le Cycle 2 (sections 8-13 du cahier des charges) est trop gros pour un seul spec.
Il est découpé en sous-cycles ; ordre des dépendances :
**2a fulltext/cache → 2b préfiltre+scoring → 2c extraction Haiku (nouveau schéma + article-liste) → escalade Sonnet.**

Ce spec couvre **2a uniquement** (section 8). Voir aussi
[`cycle-roadmap`](2026-06-29-copilot-coverage-benchmark-design.md) pour la vision.

Principe directeur transverse : « lire beaucoup d'articles, payer peu de tokens ».
Le cache d'extraction est le levier coût n°1.

## But

1. Récupérer le fulltext de façon **systématique** (toute URL pertinente), mais
   **cache-first** (jamais de refetch si déjà en base avec succès).
2. Stocker fulltext + métadonnées dans SQLite (`press.db`), requêtable.
3. **Ne jamais relancer l'IA** sur un contenu déjà extrait pour le même
   (contenu, version d'extraction, modèle) — y compris les résultats `none`.
4. Ne **jamais** bloquer définitivement un article sur une erreur IA/réseau.

## Périmètre

- **2a couvre** : tables SQLite, refonte `fulltext.py` (cache-first + métadonnées),
  module `extraction_cache.py`, câblage dans `run_pipeline`.
- **2a ne couvre PAS** : changer le schéma d'extraction IA (réservé 2c) ; le scoring
  de préfiltre (2b) ; la déduplication par URL canonique ; un TTL de refetch.
- **Compatibilité** : `fetch_text(url) -> str` est **conservé** (signature
  inchangée) ; on ajoute `fetch_article(url) -> dict`.

## Modèle de données (nouvelles tables dans `store.py`)

```sql
CREATE TABLE IF NOT EXISTS articles (
    raw_url        TEXT PRIMARY KEY,
    final_url      TEXT,
    canonical_url  TEXT,
    title          TEXT,
    source_domain  TEXT,
    published_at   TEXT,
    fetched_at     TEXT NOT NULL,
    fulltext       TEXT,
    fulltext_hash  TEXT,           -- SHA-256[:16] du fulltext, NULL si vide
    fetch_status   TEXT NOT NULL   -- 'ok' | 'empty' | 'error'
);

CREATE TABLE IF NOT EXISTS extractions (
    content_hash       TEXT NOT NULL,   -- SHA-256[:16] du texte EXACT envoyé au modèle
    extraction_version INTEGER NOT NULL,
    model              TEXT NOT NULL,
    status             TEXT NOT NULL,   -- 'closure' | 'none' | 'error'
    result_json        TEXT,            -- résultat sérialisé si status='closure'
    error_type         TEXT,            -- nom de l'exception si status='error'
    attempts           INTEGER NOT NULL DEFAULT 0,
    retry_after        TEXT,            -- ISO ; ne pas réessayer avant cette date
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    PRIMARY KEY (content_hash, extraction_version, model)
);
```

Migration idempotente via `CREATE TABLE IF NOT EXISTS` dans `init_db` (cohérent
avec le `_SCHEMA` existant).

## Flux fulltext (`fulltext.fetch_article`)

`fetch_article(url, fetch=None, conn=None) -> dict` renvoyant
`{raw_url, final_url, canonical_url, title, source_domain, published_at,
fetched_at, fulltext, fulltext_hash, fetch_status}`.

1. **Cache-first** : si `articles[raw_url]` existe avec `fetch_status='ok'` →
   retourne la ligne, **aucun appel réseau**.
2. Sinon télécharge : `final_url = resp.url`, `source_domain = netloc(final_url)`,
   `fulltext = trafilatura.extract(html)`, `title`/`published_at`/`canonical_url`
   via `trafilatura.extract_metadata(html)` (best-effort, champs NULL si absents).
3. `fulltext_hash = sha256(fulltext)[:16]` si fulltext non vide.
4. `fetch_status` : `'ok'` si fulltext non vide ; `'empty'` si page récupérée mais
   extraction vide ; `'error'` si exception réseau/HTTP.
5. Upsert dans `articles`. Les lignes `empty`/`error` **n'empêchent pas** un
   refetch ultérieur (cache-first ne court-circuite que `fetch_status='ok'`).

`fetch_text(url, fetch=None, cache_dir=None) -> str` : conservé ; réimplémenté en
thin wrapper qui appelle `fetch_article` et renvoie `fulltext` (chaîne vide en cas
d'échec). L'ancien cache disque `.txt` est remplacé par la table `articles`.

Le `fetch` injectable retourne désormais l'objet réponse (ou un petit objet
`{text, url}`) pour exposer `final_url` aux tests ; signature de test documentée.

## Flux cache d'extraction (`backend/extraction_cache.py`)

```python
def extract_cached(article, extract_fn, conn, *,
                   model=config.ANTHROPIC_MODEL,
                   version=config.EXTRACTION_VERSION,
                   now_fn=...) -> dict | None
```

- `content_hash = sha256(payload)[:16]` où `payload` = texte EXACT qui sera
  envoyé au modèle (titre + texte de `article`). Quand le fulltext est présent,
  il domine le payload → hash stable tant que le contenu ne change pas.
- **Lookup** `(content_hash, version, model)` :
  - `status='closure'` → **HIT**, retourne `json.loads(result_json)`, **0 appel IA**.
  - `status='none'` → **HIT**, retourne `None`, **0 appel IA** (levier coût clé).
  - `status='error'` → réessai conditionnel :
    - si `attempts < config.EXTRACTION_MAX_ATTEMPTS` **et** (`retry_after` nul
      ou `now >= retry_after`) → on rappelle l'IA ;
    - sinon → retourne `None` sans appeler l'IA (soft-skip temporaire).
  - aucune ligne → on appelle l'IA.
- **Appel IA** : `result = extract_fn(article)` sous `try/except` (ne lève jamais).
  - succès avec dict → upsert `status='closure'`, `result_json=...`,
    `attempts` inchangé.
  - succès `None` → upsert `status='none'`.
  - exception → upsert `status='error'`, `error_type=type(exc).__name__`,
    `attempts += 1`, `retry_after = now + backoff(attempts)` où
    `backoff = EXTRACTION_RETRY_BASE_MIN * 2**(attempts-1)` minutes ; retourne `None`.

Constantes `config` : `EXTRACTION_VERSION = 1`, `EXTRACTION_MAX_ATTEMPTS = 3`,
`EXTRACTION_RETRY_BASE_MIN = 60`.

## Câblage dans `run_pipeline`

- L'enrichissement utilise `fetch_article` (via `fetch_text` conservé pour le
  reste) — fulltext **systématique** : on retire le gate `len(texte) < 400`,
  on enrichit toute URL pertinente (cache-first rend les reruns gratuits).
- L'extraction passe par `extract_cached(art, extractor_fn, conn, ...)` au lieu
  d'appeler `extractor_fn` directement. `extractor_fn` reste
  `lambda art: extract(art, client=...)` (schéma inchangé).
- `store.mark_url_seen` reste pour le court-circuit rapide ; le cache
  d'extraction est la couche anti-recoût durable (survit aux reset de `seen_urls`).

## Gestion d'erreurs

- `fetch_article` : best-effort, ne lève jamais ; échecs → `fetch_status` adéquat.
- `extract_cached` : ne lève jamais ; erreurs IA → ligne `error` ré-essayable.
- Toutes les écritures DB sont des upserts idempotents.

## Tests (TDD)

`tests/test_extraction_cache.py` :
1. Miss → appelle `extract_fn` une fois, stocke `closure`, renvoie le dict.
2. `none` mis en cache → second appel ne rappelle PAS `extract_fn`, renvoie `None`.
3. `closure` mis en cache → second appel ne rappelle PAS `extract_fn`.
4. Clé inclut `model` : même contenu/version mais modèle différent → miss (rappel).
5. Clé inclut `extraction_version` : version différente → miss.
6. `error` : 1er échec → `status=error`, `attempts=1`, `retry_after` futur ;
   ré-appel avant `retry_after` → soft-skip (pas d'appel IA) ;
   ré-appel après `retry_after` (now_fn avancé) → rappel IA.
7. `attempts >= EXTRACTION_MAX_ATTEMPTS` → soft-skip même si `retry_after` passé.

`tests/test_fulltext.py` (étendre l'existant) :
8. `fetch_article` upsert une ligne `articles` avec hash + métadonnées (fetch mocké).
9. Cache-first : 2e `fetch_article` sur une URL `fetch_status='ok'` → fetch mock
   NON rappelé.
10. `fetch_text(url)` renvoie toujours la chaîne fulltext (compat).
11. Échec fetch → `fetch_status='error'`, fulltext vide, refetch possible.

`tests/test_store.py` (étendre) :
12. `init_db` crée `articles` + `extractions` (idempotent sur DB existante).

Fixtures : connexion SQLite en mémoire (`:memory:`) ; `fetch` et `extract_fn`
injectés (compteurs d'appels) ; `now_fn` injecté pour piloter le temps.

## Critères de réussite 2a

- Un 2e run sur les mêmes articles n'effectue **aucun** appel IA (tout en cache,
  y compris les `none`) ni aucun refetch des URLs `ok`.
- Une erreur IA n'empêche pas la reprise au run suivant (après `retry_after`).
- `fetch_text` reste compatible ; aucun test existant cassé.
