# Veille presse — Fermetures d'agences bancaires : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire un pipeline Python qui collecte presse locale + sources officielles, extrait par IA les fermetures/fusions d'agences bancaires, les stocke en SQLite, les géocode, et exporte un `data.json` pour un front web Leaflet (carte + filtres).

**Architecture:** Deux blocs reliés par un fichier d'export. Le backend Python orchestre collecte → pré-filtre → extraction IA → dédup/stockage SQLite → géocodage → export JSON/GeoJSON. Le frontend statique (HTML/JS + Leaflet) lit l'export et affiche une carte choroplèthe par département + des points par commune, avec filtres.

**Tech Stack:** Python 3.11+, pytest, `requests`, `feedparser`, `anthropic` (SDK officiel + sorties structurées Pydantic), `pydantic`, SQLite (`sqlite3` stdlib), Base Adresse Nationale (géocodage gratuit), Leaflet (front).

## Global Constraints

- Modèle IA d'extraction : **`claude-opus-4-8`** par défaut (configurable dans `config.py` ; `claude-haiku-4-5` possible pour réduire le coût). Ne jamais coder en dur le modèle ailleurs que dans `config.py`.
- Extraction via **sorties structurées** : `client.messages.parse(..., output_config={"format": ...})` avec un modèle Pydantic. Pas de prefill assistant (rejeté en 400 sur Opus 4.8).
- Clé API lue depuis la variable d'environnement `ANTHROPIC_API_KEY` (jamais en dur).
- Toutes les dates stockées au format ISO `YYYY-MM-DD` (TEXT en SQLite).
- Géocodage et collecte : aucune clé API requise (sources gratuites).
- Tout chemin de fichier est résolu relativement à la racine du projet via `config.py` (pas de chemins en dur dispersés).
- Type de fermeture : valeurs autorisées `"fermeture"` | `"fusion"`. Statut : `"confirmé"` | `"projet"` | `"rumeur"`. Fiabilité : entier 1–5.
- Pipeline **idempotent** : relancer `run.py` ne crée pas de doublons (cache d'URLs + clé de dédup déterministe).

---

### Task 1: Scaffolding du projet + configuration

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Create: `backend/__init__.py`
- Create: `backend/collectors/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: rien.
- Produces: `config.py` exposant les constantes : `ROOT` (Path), `DB_PATH` (Path), `EXPORT_DIR` (Path), `CACHE_DIR` (Path), `DATA_JSON` (Path), `GEOJSON_PATH` (Path), `ANTHROPIC_MODEL` (str), `ENSEIGNES` (list[str]), `TERMES_FERMETURE` (list[str]), `DEPARTEMENTS` (dict[str,str] code→nom).

- [ ] **Step 1: Écrire le test**

```python
# tests/test_config.py
import config

def test_chemins_sous_racine():
    assert config.DB_PATH.parent == config.ROOT / "data"
    assert config.DATA_JSON == config.EXPORT_DIR / "data.json"

def test_modele_par_defaut():
    assert config.ANTHROPIC_MODEL == "claude-opus-4-8"

def test_listes_non_vides():
    assert len(config.ENSEIGNES) >= 5
    assert "fermeture" in [t.lower() for t in config.TERMES_FERMETURE]
    assert config.DEPARTEMENTS["35"] == "Ille-et-Vilaine"
    assert len(config.DEPARTEMENTS) >= 96
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Écrire `requirements.txt`**

```
requests>=2.31
feedparser>=6.0
anthropic>=0.69
pydantic>=2.0
pytest>=8.0
```

- [ ] **Step 4: Écrire `config.py`**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
EXPORT_DIR = DATA_DIR / "export"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "press.db"
DATA_JSON = EXPORT_DIR / "data.json"
GEOJSON_PATH = EXPORT_DIR / "departements.geojson"

# Modèle IA d'extraction. claude-haiku-4-5 = moins cher pour le volume.
ANTHROPIC_MODEL = "claude-opus-4-8"

ENSEIGNES = [
    "Crédit Agricole", "BNP Paribas", "Société Générale", "Banque Populaire",
    "Caisse d'Épargne", "Crédit Mutuel", "CIC", "LCL", "La Banque Postale",
    "Crédit du Nord", "HSBC", "Boursorama", "Banque Postale",
]

TERMES_FERMETURE = [
    "fermeture", "ferme", "fermer", "fermé", "fusion", "fusionne",
    "regroupement", "regroupe", "supprime", "suppression", "transfert",
]

# Codes département → nom (métropole + DROM). Liste complète requise.
DEPARTEMENTS = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes",
    "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron",
    "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud",
    "2B": "Haute-Corse", "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse",
    "24": "Dordogne", "25": "Doubs", "26": "Drôme", "27": "Eure", "28": "Eure-et-Loir",
    "29": "Finistère", "30": "Gard", "31": "Haute-Garonne", "32": "Gers",
    "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine", "36": "Indre",
    "37": "Indre-et-Loire", "38": "Isère", "39": "Jura", "40": "Landes",
    "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire", "44": "Loire-Atlantique",
    "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne", "48": "Lozère",
    "49": "Maine-et-Loire", "50": "Manche", "51": "Marne", "52": "Haute-Marne",
    "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse", "56": "Morbihan",
    "57": "Moselle", "58": "Nièvre", "59": "Nord", "60": "Oise", "61": "Orne",
    "62": "Pas-de-Calais", "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques",
    "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales", "67": "Bas-Rhin",
    "68": "Haut-Rhin", "69": "Rhône", "70": "Haute-Saône", "71": "Saône-et-Loire",
    "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie", "75": "Paris",
    "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres",
    "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse",
    "85": "Vendée", "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne",
    "90": "Territoire de Belfort", "91": "Essonne", "92": "Hauts-de-Seine",
    "93": "Seine-Saint-Denis", "94": "Val-de-Marne", "95": "Val-d'Oise",
    "971": "Guadeloupe", "972": "Martinique", "973": "Guyane", "974": "La Réunion",
    "976": "Mayotte",
}
```

Crée aussi les fichiers `__init__.py` vides (`backend/`, `backend/collectors/`, `tests/`).

- [ ] **Step 5: Lancer le test, vérifier le succès, committer**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (3 tests)

```bash
git add requirements.txt config.py backend/ tests/
git commit -m "feat: scaffolding projet + configuration"
```

---

### Task 2: Pré-filtre par mots-clés

**Files:**
- Create: `backend/prefilter.py`
- Create: `tests/test_prefilter.py`

**Interfaces:**
- Consumes: `config.ENSEIGNES`, `config.TERMES_FERMETURE`.
- Produces: `is_relevant(article: dict) -> bool`. Un `article` est un dict avec au moins les clés `titre` (str) et `texte` (str). Retourne `True` seulement si le texte combiné (titre + texte, insensible à la casse/accents) contient **au moins une enseigne ET au moins un terme de fermeture**.

- [ ] **Step 1: Écrire le test**

```python
# tests/test_prefilter.py
from backend.prefilter import is_relevant

def test_garde_article_pertinent():
    art = {"titre": "La Société Générale ferme son agence",
           "texte": "L'agence de Rennes va fermer en juin."}
    assert is_relevant(art) is True

def test_rejette_sans_enseigne():
    art = {"titre": "Fermeture d'une boulangerie", "texte": "Le commerce ferme."}
    assert is_relevant(art) is False

def test_rejette_sans_terme_fermeture():
    art = {"titre": "Le Crédit Agricole recrute", "texte": "Nouvelle embauche."}
    assert is_relevant(art) is False

def test_insensible_accents_casse():
    art = {"titre": "CREDIT MUTUEL", "texte": "agence fermee a Brest"}
    assert is_relevant(art) is True
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_prefilter.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'backend.prefilter'`

- [ ] **Step 3: Écrire l'implémentation**

```python
# backend/prefilter.py
import unicodedata
import config


def _normalise(texte: str) -> str:
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn"
    )
    return sans_accents.lower()


_ENSEIGNES_N = [_normalise(e) for e in config.ENSEIGNES]
_TERMES_N = [_normalise(t) for t in config.TERMES_FERMETURE]


def is_relevant(article: dict) -> bool:
    contenu = _normalise(f"{article.get('titre', '')} {article.get('texte', '')}")
    a_enseigne = any(e in contenu for e in _ENSEIGNES_N)
    a_terme = any(t in contenu for t in _TERMES_N)
    return a_enseigne and a_terme
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `python -m pytest tests/test_prefilter.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Committer**

```bash
git add backend/prefilter.py tests/test_prefilter.py
git commit -m "feat: pré-filtre par mots-clés enseigne + fermeture"
```

---

### Task 3: Déduplication (clé déterministe)

**Files:**
- Create: `backend/dedup.py`
- Create: `tests/test_dedup.py`

**Interfaces:**
- Consumes: rien (fonctions pures).
- Produces:
  - `closure_id(banque: str, commune: str, type_: str) -> str` : hash SHA-256 (16 premiers caractères hex) calculé sur les 3 champs normalisés (minuscule, sans accents, espaces réduits). Déterministe et stable.
  - `normalise_cle(valeur: str) -> str` : normalisation utilisée pour la clé.

- [ ] **Step 1: Écrire le test**

```python
# tests/test_dedup.py
from backend.dedup import closure_id, normalise_cle

def test_id_stable_et_deterministe():
    a = closure_id("Société Générale", "Rennes", "fermeture")
    b = closure_id("Société Générale", "Rennes", "fermeture")
    assert a == b
    assert len(a) == 16

def test_id_insensible_casse_accents_espaces():
    a = closure_id("Société Générale", "Rennes", "fermeture")
    b = closure_id("societe generale ", " RENNES", "Fermeture")
    assert a == b

def test_id_distinct_si_type_differe():
    assert closure_id("BNP", "Lyon", "fermeture") != closure_id("BNP", "Lyon", "fusion")

def test_normalise_cle():
    assert normalise_cle("  Société  Générale ") == "societe generale"
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_dedup.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'backend.dedup'`

- [ ] **Step 3: Écrire l'implémentation**

```python
# backend/dedup.py
import hashlib
import re
import unicodedata


def normalise_cle(valeur: str) -> str:
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", valeur)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sans_accents.lower()).strip()


def closure_id(banque: str, commune: str, type_: str) -> str:
    base = "|".join(normalise_cle(v) for v in (banque, commune, type_))
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `python -m pytest tests/test_dedup.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Committer**

```bash
git add backend/dedup.py tests/test_dedup.py
git commit -m "feat: clé de déduplication déterministe"
```

---

### Task 4: Stockage SQLite

**Files:**
- Create: `backend/store.py`
- Create: `tests/test_store.py`

**Interfaces:**
- Consumes: `backend.dedup.closure_id`.
- Produces:
  - `init_db(path) -> sqlite3.Connection` : crée les tables `closures`, `sources`, `seen_urls` si absentes ; active les clés étrangères ; retourne la connexion.
  - `upsert_closure(conn, closure: dict) -> str` : insère ou met à jour une fermeture (clé = `closure["id"]`). En cas de conflit, garde la fiabilité maximale et complète les champs `NULL`. Retourne l'`id`.
  - `add_source(conn, closure_id: str, source: dict) -> None` : insère une source liée (ignore si l'URL existe déjà pour cette fermeture).
  - `is_url_seen(conn, url: str) -> bool` / `mark_url_seen(conn, url: str) -> None` : cache d'URLs traitées.
  - Champs `closures` : `id, banque, commune, code_insee, departement, type, date_annonce, date_fermeture, statut, fiabilite, lat, lon, citation, created_at`.
  - Champs `sources` : `id (autoincrement), closure_id, url, titre, source, date`.

- [ ] **Step 1: Écrire le test**

```python
# tests/test_store.py
import backend.store as store

def _closure(**kw):
    base = dict(id="abc123", banque="BNP", commune="Lyon", code_insee=None,
                departement="69", type="fermeture", date_annonce="2026-01-10",
                date_fermeture=None, statut="projet", fiabilite=3,
                lat=None, lon=None, citation="...")
    base.update(kw)
    return base

def test_init_cree_tables(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    noms = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"closures", "sources", "seen_urls"} <= noms

def test_upsert_puis_lecture(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    cid = store.upsert_closure(conn, _closure())
    assert cid == "abc123"
    row = conn.execute("SELECT banque, fiabilite FROM closures WHERE id=?", (cid,)).fetchone()
    assert row == ("BNP", 3)

def test_upsert_garde_fiabilite_max(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, _closure(fiabilite=2))
    store.upsert_closure(conn, _closure(fiabilite=5))
    fiab = conn.execute("SELECT fiabilite FROM closures WHERE id='abc123'").fetchone()[0]
    assert fiab == 5

def test_upsert_complete_champs_nuls(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, _closure(date_fermeture=None))
    store.upsert_closure(conn, _closure(date_fermeture="2026-06-30"))
    val = conn.execute("SELECT date_fermeture FROM closures WHERE id='abc123'").fetchone()[0]
    assert val == "2026-06-30"

def test_sources_dedupliquees(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, _closure())
    s = dict(url="http://x", titre="t", source="OF", date="2026-01-10")
    store.add_source(conn, "abc123", s)
    store.add_source(conn, "abc123", s)
    n = conn.execute("SELECT COUNT(*) FROM sources WHERE closure_id='abc123'").fetchone()[0]
    assert n == 1

def test_cache_urls(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    assert store.is_url_seen(conn, "http://a") is False
    store.mark_url_seen(conn, "http://a")
    assert store.is_url_seen(conn, "http://a") is True
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'backend.store'`

- [ ] **Step 3: Écrire l'implémentation**

```python
# backend/store.py
import sqlite3
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS closures (
    id TEXT PRIMARY KEY,
    banque TEXT NOT NULL,
    commune TEXT NOT NULL,
    code_insee TEXT,
    departement TEXT,
    type TEXT NOT NULL,
    date_annonce TEXT,
    date_fermeture TEXT,
    statut TEXT,
    fiabilite INTEGER,
    lat REAL,
    lon REAL,
    citation TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    closure_id TEXT NOT NULL REFERENCES closures(id),
    url TEXT NOT NULL,
    titre TEXT,
    source TEXT,
    date TEXT,
    UNIQUE(closure_id, url)
);
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY
);
"""


def init_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def upsert_closure(conn: sqlite3.Connection, closure: dict) -> str:
    existing = conn.execute(
        "SELECT fiabilite, code_insee, date_fermeture, lat, lon FROM closures WHERE id=?",
        (closure["id"],),
    ).fetchone()
    if existing is None:
        conn.execute(
            """INSERT INTO closures
            (id, banque, commune, code_insee, departement, type, date_annonce,
             date_fermeture, statut, fiabilite, lat, lon, citation, created_at)
            VALUES (:id,:banque,:commune,:code_insee,:departement,:type,:date_annonce,
                    :date_fermeture,:statut,:fiabilite,:lat,:lon,:citation,:created_at)""",
            {**closure, "created_at": datetime.now(timezone.utc).isoformat()},
        )
    else:
        fiab_max = max(existing[0] or 0, closure.get("fiabilite") or 0)
        conn.execute(
            """UPDATE closures SET
                fiabilite=?,
                code_insee=COALESCE(code_insee, ?),
                date_fermeture=COALESCE(date_fermeture, ?),
                lat=COALESCE(lat, ?),
                lon=COALESCE(lon, ?)
               WHERE id=?""",
            (fiab_max, closure.get("code_insee"), closure.get("date_fermeture"),
             closure.get("lat"), closure.get("lon"), closure["id"]),
        )
    conn.commit()
    return closure["id"]


def add_source(conn: sqlite3.Connection, closure_id: str, source: dict) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO sources (closure_id, url, titre, source, date)
           VALUES (?,?,?,?,?)""",
        (closure_id, source["url"], source.get("titre"),
         source.get("source"), source.get("date")),
    )
    conn.commit()


def is_url_seen(conn: sqlite3.Connection, url: str) -> bool:
    return conn.execute("SELECT 1 FROM seen_urls WHERE url=?", (url,)).fetchone() is not None


def mark_url_seen(conn: sqlite3.Connection, url: str) -> None:
    conn.execute("INSERT OR IGNORE INTO seen_urls (url) VALUES (?)", (url,))
    conn.commit()
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Committer**

```bash
git add backend/store.py tests/test_store.py
git commit -m "feat: stockage SQLite (closures, sources, cache urls)"
```

---

### Task 5: Collecteur Google News (RSS)

**Files:**
- Create: `backend/collectors/google_news.py`
- Create: `tests/test_google_news.py`
- Create: `tests/fixtures/google_news_sample.xml`

**Interfaces:**
- Consumes: `config.DEPARTEMENTS`.
- Produces:
  - `build_query(departement_nom: str) -> str` : construit la requête Google News (enseignes bancaires + termes fermeture + nom du département).
  - `parse_feed(xml: str, source_label: str = "Google News") -> list[dict]` : parse un flux RSS (via `feedparser`) en liste d'articles normalisés `{titre, texte, url, date, source, departement}` (`departement` laissé à `None` ici, rempli par l'appelant).
  - `collect(fetch=...) -> list[dict]` : pour chaque département, télécharge le flux et agrège les articles ; `fetch` est une fonction injectable `(url) -> str` (défaut : `requests.get`), ce qui rend la collecte testable sans réseau.

- [ ] **Step 1: Écrire la fixture + le test**

Crée `tests/fixtures/google_news_sample.xml` :

```xml
<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>La Société Générale ferme son agence de Rennes</title>
  <link>https://exemple.fr/article-1</link>
  <pubDate>Wed, 10 Jan 2026 08:00:00 GMT</pubDate>
  <description>L'agence va fermer.</description>
</item>
<item>
  <title>BNP Paribas regroupe deux agences à Lyon</title>
  <link>https://exemple.fr/article-2</link>
  <pubDate>Thu, 11 Jan 2026 09:00:00 GMT</pubDate>
  <description>Regroupement annoncé.</description>
</item>
</channel></rss>
```

```python
# tests/test_google_news.py
from pathlib import Path
from backend.collectors import google_news

FIXT = Path(__file__).parent / "fixtures" / "google_news_sample.xml"

def test_build_query_contient_departement():
    q = google_news.build_query("Ille-et-Vilaine")
    assert "Ille-et-Vilaine" in q

def test_parse_feed():
    arts = google_news.parse_feed(FIXT.read_text(encoding="utf-8"))
    assert len(arts) == 2
    a = arts[0]
    assert a["titre"].startswith("La Société Générale")
    assert a["url"] == "https://exemple.fr/article-1"
    assert a["source"] == "Google News"
    assert set(a) >= {"titre", "texte", "url", "date", "source", "departement"}

def test_collect_injecte_fetch():
    xml = FIXT.read_text(encoding="utf-8")
    arts = google_news.collect(fetch=lambda url: xml)
    # 2 articles par département × nb départements
    assert len(arts) == 2 * len(__import__("config").DEPARTEMENTS)
    assert all(a["departement"] is not None for a in arts)
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_google_news.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire l'implémentation**

```python
# backend/collectors/google_news.py
import urllib.parse
import feedparser
import requests
import config

_ENSEIGNES_OR = " OR ".join(f'"{e}"' for e in config.ENSEIGNES)
_TERMES_OR = " OR ".join(["fermeture", "fermée", "fusion", "regroupement"])


def build_query(departement_nom: str) -> str:
    return f'({_ENSEIGNES_OR}) ({_TERMES_OR}) agence "{departement_nom}"'


def _feed_url(departement_nom: str) -> str:
    q = urllib.parse.quote(build_query(departement_nom))
    return f"https://news.google.com/rss/search?q={q}&hl=fr&gl=FR&ceid=FR:fr"


def parse_feed(xml: str, source_label: str = "Google News") -> list[dict]:
    parsed = feedparser.parse(xml)
    articles = []
    for entry in parsed.entries:
        articles.append({
            "titre": entry.get("title", ""),
            "texte": entry.get("description", ""),
            "url": entry.get("link", ""),
            "date": entry.get("published", ""),
            "source": source_label,
            "departement": None,
        })
    return articles


def _default_fetch(url: str) -> str:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "veille-presse/1.0"})
    resp.raise_for_status()
    return resp.text


def collect(fetch=_default_fetch) -> list[dict]:
    resultats = []
    for code, nom in config.DEPARTEMENTS.items():
        try:
            xml = fetch(_feed_url(nom))
        except Exception as exc:  # une source en panne ne casse pas le run
            print(f"[google_news] {code} {nom}: erreur {exc}")
            continue
        for art in parse_feed(xml):
            art["departement"] = code
            resultats.append(art)
    return resultats
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `python -m pytest tests/test_google_news.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Committer**

```bash
git add backend/collectors/google_news.py tests/test_google_news.py tests/fixtures/google_news_sample.xml
git commit -m "feat: collecteur Google News RSS par département"
```

---

### Task 6: Collecteur GDELT

**Files:**
- Create: `backend/collectors/gdelt.py`
- Create: `tests/test_gdelt.py`
- Create: `tests/fixtures/gdelt_sample.json`

**Interfaces:**
- Consumes: rien (filtrage par mots-clés en aval via prefilter).
- Produces:
  - `parse_response(payload: dict) -> list[dict]` : transforme la réponse JSON GDELT Doc API (clé `articles`) en articles normalisés `{titre, texte, url, date, source, departement}` (`source="GDELT"`, `departement=None`, `texte=""` car GDELT ne fournit pas le corps).
  - `collect(fetch=...) -> list[dict]` : interroge l'API GDELT Doc 2.0 (`https://api.gdeltproject.org/api/v2/doc/doc`) avec une requête fermeture+banque en français ; `fetch` injectable `(url) -> dict`.

- [ ] **Step 1: Écrire la fixture + le test**

Crée `tests/fixtures/gdelt_sample.json` :

```json
{"articles": [
  {"title": "Crédit Mutuel ferme une agence", "url": "https://ex.fr/g1",
   "seendate": "20260112T080000Z", "domain": "ouest-france.fr"},
  {"title": "Fusion d'agences LCL", "url": "https://ex.fr/g2",
   "seendate": "20260113T090000Z", "domain": "lefigaro.fr"}
]}
```

```python
# tests/test_gdelt.py
import json
from pathlib import Path
from backend.collectors import gdelt

FIXT = Path(__file__).parent / "fixtures" / "gdelt_sample.json"

def test_parse_response():
    payload = json.loads(FIXT.read_text(encoding="utf-8"))
    arts = gdelt.parse_response(payload)
    assert len(arts) == 2
    a = arts[0]
    assert a["titre"] == "Crédit Mutuel ferme une agence"
    assert a["url"] == "https://ex.fr/g1"
    assert a["source"] == "GDELT"
    assert set(a) >= {"titre", "texte", "url", "date", "source", "departement"}

def test_parse_response_vide():
    assert gdelt.parse_response({}) == []

def test_collect_injecte_fetch():
    payload = json.loads(FIXT.read_text(encoding="utf-8"))
    arts = gdelt.collect(fetch=lambda url: payload)
    assert len(arts) == 2
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_gdelt.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire l'implémentation**

```python
# backend/collectors/gdelt.py
import urllib.parse
import requests

_QUERY = '(agence banque) (fermeture OR fusion) sourcelang:french'
_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"


def parse_response(payload: dict) -> list[dict]:
    articles = []
    for item in payload.get("articles", []):
        articles.append({
            "titre": item.get("title", ""),
            "texte": "",
            "url": item.get("url", ""),
            "date": item.get("seendate", ""),
            "source": "GDELT",
            "departement": None,
        })
    return articles


def _url() -> str:
    params = urllib.parse.urlencode({
        "query": _QUERY, "mode": "ArtList", "format": "json",
        "maxrecords": "250", "timespan": "1w",
    })
    return f"{_BASE}?{params}"


def _default_fetch(url: str) -> dict:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "veille-presse/1.0"})
    resp.raise_for_status()
    return resp.json()


def collect(fetch=_default_fetch) -> list[dict]:
    try:
        payload = fetch(_url())
    except Exception as exc:
        print(f"[gdelt] erreur {exc}")
        return []
    return parse_response(payload)
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `python -m pytest tests/test_gdelt.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Committer**

```bash
git add backend/collectors/gdelt.py tests/test_gdelt.py tests/fixtures/gdelt_sample.json
git commit -m "feat: collecteur GDELT (Doc API)"
```

---

### Task 7: Collecteur officiel (registre ACPR / REGAFI)

**Files:**
- Create: `backend/collectors/official.py`
- Create: `tests/test_official.py`
- Create: `tests/fixtures/regafi_sample.csv`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `parse_csv(contenu: str) -> list[dict]` : parse un export CSV du registre (colonnes attendues : `denomination`, `commune`, `code_postal`, `statut`) et renvoie des « articles » normalisés `{titre, texte, url, date, source, departement}` où `source="ACPR"`, `departement` = 2 premiers chiffres du code postal, `url` = chaîne stable construite (ex. `acpr://<denomination>/<commune>`). Ne garde que les lignes au statut signalant un retrait (`statut` contenant « radié » / « cessation »).
  - `collect(loader=...) -> list[dict]` : charge le CSV (par défaut depuis un fichier local `data/cache/regafi.csv` si présent, sinon retourne `[]` avec un message) ; `loader` injectable `() -> str | None`.

> Note d'implémentation : le registre REGAFI se télécharge manuellement depuis le site ACPR. Le collecteur lit donc un fichier déposé localement plutôt que de scraper. Documenter ce point dans le code.

- [ ] **Step 1: Écrire la fixture + le test**

Crée `tests/fixtures/regafi_sample.csv` :

```csv
denomination,commune,code_postal,statut
Société Générale Agence Rennes Centre,Rennes,35000,Radié
BNP Paribas Lyon Part-Dieu,Lyon,69003,Actif
Crédit Agricole Brest,Brest,29200,Cessation d'activité
```

```python
# tests/test_official.py
from pathlib import Path
from backend.collectors import official

FIXT = Path(__file__).parent / "fixtures" / "regafi_sample.csv"

def test_parse_csv_garde_retraits():
    arts = official.parse_csv(FIXT.read_text(encoding="utf-8"))
    # 2 lignes en retrait (Radié + Cessation), pas l'Actif
    assert len(arts) == 2
    communes = {a["commune"] for a in arts}
    assert communes == {"Rennes", "Brest"}

def test_parse_csv_departement_depuis_cp():
    arts = official.parse_csv(FIXT.read_text(encoding="utf-8"))
    rennes = next(a for a in arts if a["commune"] == "Rennes")
    assert rennes["departement"] == "35"
    assert rennes["source"] == "ACPR"
    assert set(rennes) >= {"titre", "texte", "url", "date", "source", "departement"}

def test_collect_sans_fichier_retourne_vide():
    assert official.collect(loader=lambda: None) == []
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_official.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire l'implémentation**

```python
# backend/collectors/official.py
# Le registre REGAFI (ACPR/Banque de France) se télécharge manuellement
# depuis https://www.regafi.fr puis se dépose dans data/cache/regafi.csv.
import csv
import io
import config

_TERMES_RETRAIT = ("radié", "radie", "cessation")


def parse_csv(contenu: str) -> list[dict]:
    lecteur = csv.DictReader(io.StringIO(contenu))
    articles = []
    for ligne in lecteur:
        statut = (ligne.get("statut") or "").lower()
        if not any(t in statut for t in _TERMES_RETRAIT):
            continue
        commune = (ligne.get("commune") or "").strip()
        denomination = (ligne.get("denomination") or "").strip()
        cp = (ligne.get("code_postal") or "").strip()
        departement = cp[:2] if cp else None
        articles.append({
            "titre": f"{denomination} — {ligne.get('statut')}",
            "texte": f"{denomination} à {commune} ({cp}) : {ligne.get('statut')}.",
            "url": f"acpr://{denomination}/{commune}",
            "date": "",
            "source": "ACPR",
            "departement": departement,
        })
    return articles


def _default_loader() -> str | None:
    chemin = config.CACHE_DIR / "regafi.csv"
    if chemin.exists():
        return chemin.read_text(encoding="utf-8")
    print("[official] data/cache/regafi.csv absent — collecteur officiel ignoré")
    return None


def collect(loader=_default_loader) -> list[dict]:
    contenu = loader()
    if not contenu:
        return []
    return parse_csv(contenu)
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `python -m pytest tests/test_official.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Committer**

```bash
git add backend/collectors/official.py tests/test_official.py tests/fixtures/regafi_sample.csv
git commit -m "feat: collecteur officiel ACPR/REGAFI (CSV local)"
```

---

### Task 8: Extracteur IA (API Claude, sorties structurées)

**Files:**
- Create: `backend/extractor.py`
- Create: `tests/test_extractor.py`

**Interfaces:**
- Consumes: `config.ANTHROPIC_MODEL`, `backend.dedup.closure_id`.
- Produces:
  - Modèle Pydantic `Extraction` : champs `concerne_banque: bool`, `banque: str`, `commune: str`, `departement: str | None`, `type: Literal["fermeture","fusion"]`, `date_fermeture: str | None`, `statut: Literal["confirmé","projet","rumeur"]`, `fiabilite: int` (1–5), `citation: str`.
  - `extract(article: dict, client, model=config.ANTHROPIC_MODEL) -> dict | None` : appelle `client.messages.parse(...)`, lit `response.parsed_output`. Si `concerne_banque` est `False` → retourne `None`. Sinon retourne un dict prêt pour `store.upsert_closure` (avec `id` calculé via `closure_id`, `date_annonce` = `article["date"]` normalisée si possible sinon `None`, `code_insee=None`, `lat=None`, `lon=None`).
  - `build_messages(article: dict) -> list[dict]` : construit la liste `messages` (pas de prefill). Pure et testable.

- [ ] **Step 1: Écrire le test (client factice, aucun appel réseau)**

```python
# tests/test_extractor.py
from backend.extractor import extract, build_messages, Extraction

class FakeResp:
    def __init__(self, parsed):
        self.parsed_output = parsed

class FakeMessages:
    def __init__(self, parsed):
        self._parsed = parsed
    def parse(self, **kw):
        return FakeResp(self._parsed)

class FakeClient:
    def __init__(self, parsed):
        self.messages = FakeMessages(parsed)

def _article():
    return {"titre": "La Société Générale ferme son agence de Rennes",
            "texte": "L'agence fermera le 30 juin 2026.",
            "url": "http://x", "date": "2026-01-10",
            "source": "Google News", "departement": "35"}

def test_build_messages_sans_prefill():
    msgs = build_messages(_article())
    assert msgs[0]["role"] == "user"
    assert msgs[-1]["role"] != "assistant"
    assert "Société Générale" in msgs[0]["content"]

def test_extract_article_pertinent():
    parsed = Extraction(concerne_banque=True, banque="Société Générale",
                        commune="Rennes", departement="35", type="fermeture",
                        date_fermeture="2026-06-30", statut="projet",
                        fiabilite=4, citation="L'agence fermera le 30 juin 2026.")
    res = extract(_article(), client=FakeClient(parsed))
    assert res["banque"] == "Société Générale"
    assert res["type"] == "fermeture"
    assert res["date_annonce"] == "2026-01-10"
    assert len(res["id"]) == 16
    assert res["lat"] is None and res["code_insee"] is None

def test_extract_rejette_hors_sujet():
    parsed = Extraction(concerne_banque=False, banque="", commune="",
                        departement=None, type="fermeture", date_fermeture=None,
                        statut="rumeur", fiabilite=1, citation="")
    assert extract(_article(), client=FakeClient(parsed)) is None
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_extractor.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'backend.extractor'`

- [ ] **Step 3: Écrire l'implémentation**

```python
# backend/extractor.py
from typing import Literal, Optional
from pydantic import BaseModel, Field
import config
from backend.dedup import closure_id

_INSTRUCTIONS = (
    "Tu analyses un article de presse français. Détermine s'il annonce la "
    "FERMETURE ou la FUSION/REGROUPEMENT d'une agence bancaire physique en France. "
    "Si oui, renvoie les informations structurées. Si l'article ne concerne pas "
    "une fermeture/fusion d'agence bancaire, mets concerne_banque=false. "
    "fiabilite: 1 (rumeur vague) à 5 (annonce officielle confirmée). "
    "citation: la phrase exacte de l'article qui justifie la fermeture/fusion."
)


class Extraction(BaseModel):
    concerne_banque: bool = Field(description="True si fermeture/fusion d'agence bancaire")
    banque: str
    commune: str
    departement: Optional[str] = None
    type: Literal["fermeture", "fusion"]
    date_fermeture: Optional[str] = Field(default=None, description="ISO YYYY-MM-DD si connue")
    statut: Literal["confirmé", "projet", "rumeur"]
    fiabilite: int = Field(ge=1, le=5)
    citation: str


def build_messages(article: dict) -> list[dict]:
    corps = (
        f"{_INSTRUCTIONS}\n\n"
        f"TITRE: {article.get('titre','')}\n"
        f"TEXTE: {article.get('texte','')}\n"
        f"DÉPARTEMENT (indice): {article.get('departement')}"
    )
    return [{"role": "user", "content": corps}]


def extract(article: dict, client, model: str = config.ANTHROPIC_MODEL) -> Optional[dict]:
    response = client.messages.parse(
        model=model,
        max_tokens=1024,
        messages=build_messages(article),
        output_config={"format": Extraction},
    )
    data: Extraction = response.parsed_output
    if data is None or not data.concerne_banque:
        return None
    return {
        "id": closure_id(data.banque, data.commune, data.type),
        "banque": data.banque,
        "commune": data.commune,
        "code_insee": None,
        "departement": data.departement or article.get("departement"),
        "type": data.type,
        "date_annonce": article.get("date") or None,
        "date_fermeture": data.date_fermeture,
        "statut": data.statut,
        "fiabilite": data.fiabilite,
        "lat": None,
        "lon": None,
        "citation": data.citation,
    }
```

> Note : `output_config={"format": Extraction}` est accepté par `messages.parse` (helper Pydantic du SDK). Sur `claude-opus-4-8` et `claude-haiku-4-5` les sorties structurées sont supportées.

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `python -m pytest tests/test_extractor.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Committer**

```bash
git add backend/extractor.py tests/test_extractor.py
git commit -m "feat: extracteur IA (API Claude, sorties structurées Pydantic)"
```

---

### Task 9: Géocodage (Base Adresse Nationale, avec cache)

**Files:**
- Create: `backend/geocode.py`
- Create: `tests/test_geocode.py`

**Interfaces:**
- Consumes: `config.CACHE_DIR`.
- Produces:
  - `parse_ban(payload: dict) -> tuple[float, float] | None` : extrait `(lat, lon)` de la première `feature` d'une réponse BAN ; `None` si vide.
  - `geocode_commune(commune, departement=None, fetch=..., cache=None) -> tuple[float,float] | None` : interroge `https://api-adresse.data.gouv.fr/search/` (type=municipality) ; `fetch` injectable `(url) -> dict` ; `cache` est un dict mutable optionnel (clé `commune|dept`) pour éviter les appels répétés dans un run.

- [ ] **Step 1: Écrire le test**

```python
# tests/test_geocode.py
from backend import geocode

BAN_OK = {"features": [
    {"geometry": {"coordinates": [-1.6778, 48.1173]},
     "properties": {"city": "Rennes"}}
]}
BAN_VIDE = {"features": []}

def test_parse_ban():
    assert geocode.parse_ban(BAN_OK) == (48.1173, -1.6778)  # (lat, lon)

def test_parse_ban_vide():
    assert geocode.parse_ban(BAN_VIDE) is None

def test_geocode_utilise_cache():
    appels = []
    def fetch(url):
        appels.append(url)
        return BAN_OK
    cache = {}
    a = geocode.geocode_commune("Rennes", "35", fetch=fetch, cache=cache)
    b = geocode.geocode_commune("Rennes", "35", fetch=fetch, cache=cache)
    assert a == b == (48.1173, -1.6778)
    assert len(appels) == 1  # second appel servi par le cache

def test_geocode_echec_retourne_none():
    res = geocode.geocode_commune("Xyz", "99", fetch=lambda url: BAN_VIDE, cache={})
    assert res is None
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_geocode.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire l'implémentation**

```python
# backend/geocode.py
import urllib.parse
import requests

_BASE = "https://api-adresse.data.gouv.fr/search/"


def parse_ban(payload: dict):
    features = payload.get("features") or []
    if not features:
        return None
    lon, lat = features[0]["geometry"]["coordinates"]
    return (lat, lon)


def _url(commune: str, departement) -> str:
    # La BAN ne filtre pas par département sur /search municipality ;
    # on requête la commune et on prend le 1er résultat (limit=1).
    params = {"q": commune, "type": "municipality", "limit": "1"}
    return f"{_BASE}?{urllib.parse.urlencode(params)}"


def _default_fetch(url: str) -> dict:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "veille-presse/1.0"})
    resp.raise_for_status()
    return resp.json()


def geocode_commune(commune, departement=None, fetch=_default_fetch, cache=None):
    if not commune:
        return None
    cle = f"{commune}|{departement or ''}"
    if cache is not None and cle in cache:
        return cache[cle]
    try:
        payload = fetch(_url(commune, departement))
        coords = parse_ban(payload)
    except Exception as exc:
        print(f"[geocode] {commune}: erreur {exc}")
        coords = None
    if cache is not None:
        cache[cle] = coords
    return coords
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `python -m pytest tests/test_geocode.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Committer**

```bash
git add backend/geocode.py tests/test_geocode.py
git commit -m "feat: géocodage via Base Adresse Nationale avec cache"
```

---

### Task 10: Export JSON

**Files:**
- Create: `backend/export.py`
- Create: `tests/test_export.py`

**Interfaces:**
- Consumes: `backend.store` (lecture), `config.DEPARTEMENTS`.
- Produces:
  - `build_payload(conn) -> dict` : lit toutes les `closures` + leurs `sources` et renvoie `{"generated_at": ISO, "departements": {code: {nom, count}}, "closures": [...]}`. Chaque closure inclut sa liste `sources`.
  - `export_json(conn, path) -> None` : écrit `build_payload` en JSON UTF-8 indenté dans `path` (crée le dossier parent).

- [ ] **Step 1: Écrire le test**

```python
# tests/test_export.py
import json
import backend.store as store
from backend import export

def _seed(conn):
    c = dict(id="abc123", banque="BNP", commune="Lyon", code_insee="69003",
             departement="69", type="fermeture", date_annonce="2026-01-10",
             date_fermeture="2026-06-30", statut="projet", fiabilite=3,
             lat=45.76, lon=4.85, citation="...")
    store.upsert_closure(conn, c)
    store.add_source(conn, "abc123",
                     dict(url="http://x", titre="t", source="OF", date="2026-01-10"))

def test_build_payload(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    _seed(conn)
    p = export.build_payload(conn)
    assert "generated_at" in p
    assert p["departements"]["69"]["count"] == 1
    assert p["departements"]["69"]["nom"] == "Rhône"
    cl = p["closures"][0]
    assert cl["banque"] == "BNP"
    assert cl["sources"][0]["url"] == "http://x"

def test_export_json_ecrit_fichier(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    _seed(conn)
    out = tmp_path / "sub" / "data.json"
    export.export_json(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["closures"]) == 1
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_export.py -v`
Expected: FAIL avec `ModuleNotFoundError`

- [ ] **Step 3: Écrire l'implémentation**

```python
# backend/export.py
import json
from datetime import datetime, timezone
import config

_CLOSURE_COLS = ["id", "banque", "commune", "code_insee", "departement", "type",
                 "date_annonce", "date_fermeture", "statut", "fiabilite",
                 "lat", "lon", "citation", "created_at"]


def build_payload(conn) -> dict:
    closures = []
    compteur = {}
    for row in conn.execute(f"SELECT {','.join(_CLOSURE_COLS)} FROM closures"):
        cl = dict(zip(_CLOSURE_COLS, row))
        srcs = conn.execute(
            "SELECT url, titre, source, date FROM sources WHERE closure_id=?",
            (cl["id"],),
        ).fetchall()
        cl["sources"] = [
            {"url": u, "titre": t, "source": s, "date": d} for (u, t, s, d) in srcs
        ]
        closures.append(cl)
        dep = cl["departement"]
        if dep:
            compteur[dep] = compteur.get(dep, 0) + 1
    departements = {
        code: {"nom": config.DEPARTEMENTS.get(code, code), "count": compteur.get(code, 0)}
        for code in config.DEPARTEMENTS
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "departements": departements,
        "closures": closures,
    }


def export_json(conn, path) -> None:
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(conn)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `python -m pytest tests/test_export.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Committer**

```bash
git add backend/export.py tests/test_export.py
git commit -m "feat: export SQLite -> data.json (closures + compteurs par dept)"
```

---

### Task 11: Orchestrateur `run.py`

**Files:**
- Create: `backend/pipeline.py`
- Create: `run.py`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: tous les modules précédents.
- Produces:
  - `backend/pipeline.py` : `run_pipeline(conn, collectors, extractor_fn, geocoder_fn) -> dict` : fonction orchestratrice pure-injectable. Pour chaque article collecté : ignore si URL déjà vue ; applique `prefilter.is_relevant` ; appelle `extractor_fn(article)` ; si résultat, géocode la commune, `upsert_closure`, `add_source`, `mark_url_seen`. Retourne un récap `{"articles": n, "filtres": n, "extraits": n, "fermetures": n}`.
  - `run.py` : point d'entrée. Construit le client Anthropic réel, branche les collecteurs réels et l'extracteur, lance `run_pipeline`, puis `export_json`.

- [ ] **Step 1: Écrire le test (tout injecté, aucun réseau ni IA)**

```python
# tests/test_pipeline.py
import backend.store as store
from backend import pipeline

def _article(url, pertinent=True):
    if pertinent:
        return {"titre": "BNP ferme son agence", "texte": "agence fermée à Lyon",
                "url": url, "date": "2026-01-10", "source": "GN", "departement": "69"}
    return {"titre": "Météo", "texte": "soleil", "url": url, "date": "", "source": "GN",
            "departement": None}

def _extractor(article):
    return {"id": "abc123", "banque": "BNP", "commune": "Lyon", "code_insee": None,
            "departement": "69", "type": "fermeture", "date_annonce": "2026-01-10",
            "date_fermeture": None, "statut": "projet", "fiabilite": 3,
            "lat": None, "lon": None, "citation": "agence fermée à Lyon"}

def test_pipeline_complet(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    collectors = [lambda: [_article("http://1"), _article("http://2", pertinent=False)]]
    recap = pipeline.run_pipeline(
        conn, collectors,
        extractor_fn=_extractor,
        geocoder_fn=lambda commune, dept: (45.76, 4.85),
    )
    assert recap["articles"] == 2
    assert recap["filtres"] == 1   # seul l'article pertinent passe le pré-filtre
    assert recap["fermetures"] == 1
    row = conn.execute("SELECT lat, lon FROM closures WHERE id='abc123'").fetchone()
    assert row == (45.76, 4.85)

def test_pipeline_idempotent(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    collectors = [lambda: [_article("http://1")]]
    pipeline.run_pipeline(conn, collectors, _extractor, lambda c, d: (1.0, 2.0))
    recap = pipeline.run_pipeline(conn, collectors, _extractor, lambda c, d: (1.0, 2.0))
    assert recap["filtres"] == 0  # URL déjà vue -> ignorée
    n = conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0]
    assert n == 1
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'backend.pipeline'`

- [ ] **Step 3: Écrire l'implémentation**

```python
# backend/pipeline.py
from backend import prefilter, store


def run_pipeline(conn, collectors, extractor_fn, geocoder_fn) -> dict:
    recap = {"articles": 0, "filtres": 0, "extraits": 0, "fermetures": 0}
    for collect in collectors:
        try:
            articles = collect()
        except Exception as exc:
            print(f"[pipeline] collecteur en erreur: {exc}")
            continue
        for art in articles:
            recap["articles"] += 1
            url = art.get("url") or ""
            if url and store.is_url_seen(conn, url):
                continue
            if not prefilter.is_relevant(art):
                if url:
                    store.mark_url_seen(conn, url)
                continue
            recap["filtres"] += 1
            try:
                resultat = extractor_fn(art)
            except Exception as exc:
                print(f"[pipeline] extraction en erreur ({url}): {exc}")
                continue
            if url:
                store.mark_url_seen(conn, url)
            if resultat is None:
                continue
            recap["extraits"] += 1
            coords = geocoder_fn(resultat["commune"], resultat.get("departement"))
            if coords:
                resultat["lat"], resultat["lon"] = coords
            store.upsert_closure(conn, resultat)
            store.add_source(conn, resultat["id"], {
                "url": url, "titre": art.get("titre"),
                "source": art.get("source"), "date": art.get("date"),
            })
            recap["fermetures"] += 1
    return recap
```

```python
# run.py
import anthropic
import config
from backend import store, export, geocode
from backend.pipeline import run_pipeline
from backend.extractor import extract
from backend.collectors import google_news, gdelt, official


def main():
    conn = store.init_db(config.DB_PATH)
    client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY
    cache_geo = {}

    collectors = [google_news.collect, gdelt.collect, official.collect]
    recap = run_pipeline(
        conn,
        collectors,
        extractor_fn=lambda art: extract(art, client=client),
        geocoder_fn=lambda commune, dept: geocode.geocode_commune(
            commune, dept, cache=cache_geo),
    )
    export.export_json(conn, config.DATA_JSON)
    print("Récapitulatif:", recap)
    print("Export écrit dans", config.DATA_JSON)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Committer**

```bash
git add backend/pipeline.py run.py tests/test_pipeline.py
git commit -m "feat: orchestrateur pipeline + point d'entrée run.py"
```

---

### Task 12: Frontend (carte Leaflet + filtres)

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/app.js`
- Create: `frontend/style.css`
- Create: `tests/test_frontend_smoke.py`

**Interfaces:**
- Consumes: `data/export/data.json` (produit par Task 11).
- Produces: une page web statique qui charge `data.json`, affiche une carte Leaflet de France avec un marqueur par closure géolocalisée et une liste filtrable (banque, type, statut, fiabilité min, département). Clic sur un marqueur/élément → détail + lien source.

> Le test côté Python est un simple smoke-test de présence/structure des fichiers (pas de runner JS). La vérification visuelle réelle se fait en ouvrant la page dans un navigateur après un `run.py`.

- [ ] **Step 1: Écrire le smoke-test**

```python
# tests/test_frontend_smoke.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"

def test_fichiers_presents():
    assert (FRONT / "index.html").exists()
    assert (FRONT / "app.js").exists()
    assert (FRONT / "style.css").exists()

def test_index_reference_leaflet_et_app():
    html = (FRONT / "index.html").read_text(encoding="utf-8")
    assert "leaflet" in html.lower()
    assert "app.js" in html

def test_app_charge_data_json():
    js = (FRONT / "app.js").read_text(encoding="utf-8")
    assert "data.json" in js
    assert "L.map" in js
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python -m pytest tests/test_frontend_smoke.py -v`
Expected: FAIL avec `AssertionError` (fichiers absents)

- [ ] **Step 3: Écrire les fichiers frontend**

```html
<!-- frontend/index.html -->
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Veille — Fermetures d'agences bancaires</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <header>
    <h1>Fermetures &amp; fusions d'agences bancaires</h1>
    <div id="filtres">
      <label>Banque <select id="f-banque"><option value="">Toutes</option></select></label>
      <label>Type
        <select id="f-type">
          <option value="">Tous</option>
          <option value="fermeture">Fermeture</option>
          <option value="fusion">Fusion</option>
        </select>
      </label>
      <label>Statut
        <select id="f-statut">
          <option value="">Tous</option>
          <option value="confirmé">Confirmé</option>
          <option value="projet">Projet</option>
          <option value="rumeur">Rumeur</option>
        </select>
      </label>
      <label>Fiabilité min
        <select id="f-fiab">
          <option value="1">1+</option><option value="2">2+</option>
          <option value="3">3+</option><option value="4">4+</option>
          <option value="5">5</option>
        </select>
      </label>
    </div>
  </header>
  <main>
    <div id="map"></div>
    <aside id="liste"></aside>
  </main>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="app.js"></script>
</body>
</html>
```

```css
/* frontend/style.css */
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; color: #1a1a1a; }
header { padding: 12px 16px; border-bottom: 1px solid #ddd; }
h1 { font-size: 1.2rem; margin: 0 0 8px; }
#filtres { display: flex; gap: 12px; flex-wrap: wrap; font-size: .85rem; }
#filtres select { margin-left: 4px; }
main { display: flex; height: calc(100vh - 96px); }
#map { flex: 2; }
#liste { flex: 1; overflow-y: auto; padding: 8px 12px; border-left: 1px solid #ddd; }
.item { padding: 8px; border-bottom: 1px solid #eee; cursor: pointer; }
.item:hover { background: #f5f5f5; }
.item h3 { margin: 0 0 4px; font-size: .95rem; }
.item .meta { font-size: .8rem; color: #666; }
.badge { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: .7rem; }
.badge.fermeture { background: #fde2e1; color: #a11; }
.badge.fusion { background: #e1ecfd; color: #1450a0; }
```

```javascript
// frontend/app.js
let DONNEES = { closures: [] };
let map, couche;

async function init() {
  map = L.map("map").setView([46.6, 2.5], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
  }).addTo(map);
  couche = L.layerGroup().addTo(map);

  const resp = await fetch("../data/export/data.json");
  DONNEES = await resp.json();

  remplirBanques();
  ["f-banque", "f-type", "f-statut", "f-fiab"].forEach((id) =>
    document.getElementById(id).addEventListener("change", rafraichir)
  );
  rafraichir();
}

function remplirBanques() {
  const set = [...new Set(DONNEES.closures.map((c) => c.banque))].sort();
  const sel = document.getElementById("f-banque");
  set.forEach((b) => {
    const o = document.createElement("option");
    o.value = b; o.textContent = b; sel.appendChild(o);
  });
}

function filtrer() {
  const banque = document.getElementById("f-banque").value;
  const type = document.getElementById("f-type").value;
  const statut = document.getElementById("f-statut").value;
  const fiab = parseInt(document.getElementById("f-fiab").value, 10);
  return DONNEES.closures.filter((c) =>
    (!banque || c.banque === banque) &&
    (!type || c.type === type) &&
    (!statut || c.statut === statut) &&
    (c.fiabilite || 0) >= fiab
  );
}

function rafraichir() {
  const items = filtrer();
  couche.clearLayers();
  const liste = document.getElementById("liste");
  liste.innerHTML = `<p>${items.length} résultat(s)</p>`;

  items.forEach((c) => {
    if (c.lat != null && c.lon != null) {
      const m = L.marker([c.lat, c.lon]).addTo(couche);
      m.bindPopup(popupHtml(c));
    }
    const div = document.createElement("div");
    div.className = "item";
    div.innerHTML = `<h3>${c.banque} — ${c.commune}</h3>
      <span class="badge ${c.type}">${c.type}</span>
      <div class="meta">${c.departement || "?"} · ${c.statut} · fiab ${c.fiabilite}</div>`;
    div.addEventListener("click", () => {
      if (c.lat != null) map.setView([c.lat, c.lon], 12);
    });
    liste.appendChild(div);
  });
}

function popupHtml(c) {
  const src = (c.sources || [])
    .filter((s) => s.url && !s.url.startsWith("acpr://"))
    .map((s) => `<a href="${s.url}" target="_blank" rel="noopener">${s.source || "source"}</a>`)
    .join(" · ");
  return `<strong>${c.banque}</strong><br>${c.commune} (${c.departement || "?"})<br>
    ${c.type} · ${c.statut} · fiabilité ${c.fiabilite}<br>
    <em>${c.citation || ""}</em><br>${src}`;
}

init();
```

- [ ] **Step 4: Lancer le smoke-test, vérifier le succès**

Run: `python -m pytest tests/test_frontend_smoke.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Vérification visuelle + commit**

Vérification manuelle (après avoir produit un `data.json`, ou avec un `data.json` factice) :
```bash
python -m http.server 8000
# Ouvrir http://localhost:8000/frontend/index.html
```
Confirmer : la carte de France s'affiche, les filtres se peuplent, un clic sur un point ouvre le détail avec le lien source.

```bash
git add frontend/ tests/test_frontend_smoke.py
git commit -m "feat: frontend Leaflet (carte + liste filtrable)"
```

---

### Task 13: README + suite de tests complète

**Files:**
- Create: `README.md`
- Create: `.gitignore`

**Interfaces:**
- Consumes: l'ensemble du projet.
- Produces: documentation d'utilisation + ignore des artefacts.

- [ ] **Step 1: Écrire `.gitignore`**

```
__pycache__/
*.pyc
data/press.db
data/export/
data/cache/
.env
.venv/
```

- [ ] **Step 2: Écrire `README.md`**

```markdown
# Veille presse — Fermetures d'agences bancaires

Pipeline Python qui collecte la presse locale + sources officielles, extrait
par IA les fermetures/fusions d'agences bancaires par département, et alimente
une carte web (Leaflet).

## Installation
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY="sk-ant-..."

## Lancer le pipeline
    python run.py
Produit `data/export/data.json`.

## Voir la carte
    python -m http.server 8000
    # http://localhost:8000/frontend/index.html

## Source officielle (optionnelle)
Déposer un export REGAFI dans `data/cache/regafi.csv`
(colonnes : denomination, commune, code_postal, statut).

## Tests
    python -m pytest -v

## Configuration
Tout se règle dans `config.py` : enseignes suivies, mots-clés, départements,
et le modèle IA (`ANTHROPIC_MODEL`, par défaut `claude-opus-4-8` ;
`claude-haiku-4-5` pour réduire le coût en volume).
```

- [ ] **Step 3: Lancer toute la suite de tests**

Run: `python -m pytest -v`
Expected: PASS (tous les tests des tâches 1–12)

- [ ] **Step 4: Committer**

```bash
git add README.md .gitignore
git commit -m "docs: README + gitignore"
```

---

## Notes de mise en œuvre

- **Ordre des tâches** : 1 → 13 dans l'ordre. Les tâches 5/6/7 (collecteurs) sont indépendantes entre elles et peuvent être parallélisées si besoin.
- **Vérification de bout en bout** : après la Task 11, faire un vrai `python run.py` avec une clé API valide pour confirmer la chaîne complète (coût API faible grâce au pré-filtre). Inspecter `data/export/data.json` puis la carte.
- **Coût IA** : si le volume d'articles devient important, passer `ANTHROPIC_MODEL` à `claude-haiku-4-5` dans `config.py`.
- **Phase 2 (hors périmètre)** : rapport email hebdomadaire lisant la même base SQLite.
