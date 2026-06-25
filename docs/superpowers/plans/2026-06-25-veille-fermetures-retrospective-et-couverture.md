# Veille fermetures — rétrospectif depuis 2025 + couverture élargie

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire passer la veille d'un mode « prévisionnel uniquement » à un mode « fermetures effectives depuis ~18 mois glissants + prévisionnel », élargir le périmètre d'enseignes (dont La Banque Postale), et combler les goulots de rappel (texte intégral, vocabulaire, drill-down commune).

**Architecture :** Un seul paramètre `since` (défaut = aujourd'hui − 18 mois glissants) pilote à la fois la fenêtre de collecte presse ET le plancher de rétention des fermetures passées. L'extracteur cesse de jeter les fermetures déjà effectives : il les conserve si leur date/période effective est ≥ plancher, sinon il les renvoie en vigilance. Le frontend gagne une dimension temporelle (déjà fermée / à venir).

**Tech Stack :** Python 3.11+, SQLite, Pydantic, Anthropic SDK (`claude-opus-4-8`), feedparser/requests, pytest ; frontend statique MapLibre GL JS (`frontend/app.js`).

## Global Constraints

- **Fenêtre par défaut : 18 mois glissants** depuis aujourd'hui (`LOOKBACK_MONTHS_DEFAULT = 18`). Élargissable via `--lookback-months 24/30…` ou `--since YYYY-MM-DD`. La fin de fenêtre est toujours `date.today()`.
- **Le même `since` sert de plancher de rétention** des fermetures passées : on jette toute fermeture effective strictement antérieure à `since`.
- **Rétention du passé : seulement si période exploitable.** Une fermeture `deja_fermee` sans date ni période exploitable (mois/trimestre/année) ne devient PAS un point carte → elle part en vigilance (comportement déjà câblé : `extract()` renvoie `None` → `vigilance_fn`).
- **La Banque Postale est désormais SUIVIE** (retirée de `EXCLURE_BANQUES`). Ajouter aussi **Crédit Coopératif**.
- **Unités Google News `when:`** : `h`=heures, `d`=jours, `y`=années, `m`=MINUTES (PAS mois). 18 mois ≈ `548d`.
- **TDD strict, commits fréquents, DRY, YAGNI.** Lancer la suite avec `python -m pytest -q`.

---

## Carte des fichiers touchés

| Fichier | Responsabilité après le plan |
|---|---|
| `config.py` | `LOOKBACK_MONTHS_DEFAULT`, `ENSEIGNES` (+ LBP, + Crédit Coopératif), `EXCLURE_BANQUES` vidé, vocabulaire euphémismes |
| `run.py` | défaut 18 mois ; passe `since` comme `floor` à l'extracteur |
| `backend/extractor.py` | conserve `deja_fermee` ≥ plancher ; expose `statut_temporel` + `date_fermeture_approx` |
| `backend/openai_fallback.py` | schéma JSON aligné (nouveau champ) |
| `backend/store.py` | colonnes `statut_temporel`, `date_fermeture_approx` |
| `backend/export.py` | exporte les 2 nouvelles colonnes ; CSV + JSON |
| `backend/prefilter.py` | inclut marques régionales + nouvelles enseignes + euphémismes |
| `frontend/index.html`, `frontend/app.js` | filtre « Période (passée / à venir) » |
| `backend/collectors/google_news.py` | euphémismes + (Phase 3) découpage mensuel + drill-down commune |
| `backend/fulltext.py` *(nouveau, Phase 2)* | récupération + extraction du texte intégral |
| `README.md` | doc périmètre + fenêtre |

---

# PHASE 1 — Modèle temporel + périmètre enseignes (shippable seul)

C'est le cœur de la demande. À livrer en un bloc cohérent : data model + extracteur + store + export + frontend + doc.

### Task 1 : Plancher temporel par défaut à 18 mois glissants

**Files:**
- Modify: `config.py` (ajout constante)
- Modify: `run.py:19-34` (`_since_from_args`), `run.py:37-51` (`_configure_collection_window`)
- Test: `tests/test_run_window.py` (créer)

**Interfaces:**
- Produces: `config.LOOKBACK_MONTHS_DEFAULT: int = 18` ; `run._since_from_args(args) -> str` (ne renvoie plus jamais `None` : défaut = today − 18 mois).

- [ ] **Step 1 : Test d'échec — défaut = 18 mois**

```python
# tests/test_run_window.py
from datetime import date, timedelta
import run


class _Args:
    since = None
    lookback_days = None
    lookback_months = None


def test_default_since_is_18_months():
    since = run._since_from_args(_Args())
    attendu = (date.today() - timedelta(days=18 * 30)).isoformat()
    assert since == attendu


def test_explicit_since_still_wins():
    a = _Args()
    a.since = "2025-01-01"
    assert run._since_from_args(a) == "2025-01-01"
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python -m pytest tests/test_run_window.py -q`
Expected: FAIL (`_since_from_args` renvoie `None`).

- [ ] **Step 3 : Ajouter la constante dans `config.py`**

Sous `GOOGLE_NEWS_WHEN` :

```python
# Fenêtre de veille par défaut : 18 mois glissants (couvre le rétrospectif
# depuis ~début 2025 + le prévisionnel). Élargissable via --lookback-months.
LOOKBACK_MONTHS_DEFAULT = int(os.getenv("LOOKBACK_MONTHS_DEFAULT", "18"))
```

- [ ] **Step 4 : Défaut dans `run._since_from_args`**

Remplacer le `return None` final par :

```python
    return (date.today() - timedelta(days=config.LOOKBACK_MONTHS_DEFAULT * 30)).isoformat()
```

- [ ] **Step 5 : Lancer, vérifier le succès**

Run: `python -m pytest tests/test_run_window.py -q`
Expected: PASS.

- [ ] **Step 6 : Commit**

```bash
git add config.py run.py tests/test_run_window.py
git commit -m "feat: fenêtre de veille par défaut 18 mois glissants"
```

---

### Task 2 : Périmètre enseignes — ajouter La Banque Postale + Crédit Coopératif

**Files:**
- Modify: `config.py` (`ENSEIGNES`, `EXCLURE_BANQUES`)
- Modify: `backend/extractor.py:33-48` (`_CANON`)
- Test: `tests/test_extractor.py` (ajouter)

**Interfaces:**
- Consumes: `extractor.normalise_banque`.
- Produces: `config.ENSEIGNES` contient `"La Banque Postale"` et `"Crédit Coopératif"` ; `config.EXCLURE_BANQUES == []`.

- [ ] **Step 1 : Test d'échec**

```python
# tests/test_extractor.py (ajout)
import config
from backend.extractor import normalise_banque


def test_la_banque_postale_est_suivie():
    assert "La Banque Postale" in config.ENSEIGNES
    assert config.EXCLURE_BANQUES == []
    assert normalise_banque("La Banque Postale") == "La Banque Postale"


def test_credit_cooperatif_canonique():
    assert "Crédit Coopératif" in config.ENSEIGNES
    assert normalise_banque("crédit coopératif") == "Crédit Coopératif"
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `python -m pytest tests/test_extractor.py -q -k "postale or cooperatif"`
Expected: FAIL.

- [ ] **Step 3 : Mettre à jour `config.py`**

```python
ENSEIGNES = [
    "Crédit Agricole", "BNP", "Société Générale", "Banque Populaire",
    "Caisse d'Épargne", "Crédit Mutuel", "CIC", "LCL",
    "Crédit du Nord", "HSBC", "CCF", "La Banque Postale", "Crédit Coopératif",
]
```

Et vider l'exclusion :

```python
# Plus aucune enseigne exclue du suivi (La Banque Postale est désormais suivie).
EXCLURE_BANQUES: list[str] = []
```

- [ ] **Step 4 : Ajouter Crédit Coopératif au `_CANON` de `extractor.py`**

Dans le dict `_CANON`, après `"hsbc": "HSBC",` :

```python
    "credit cooperatif": "Crédit Coopératif",
    "la banque postale": "La Banque Postale",
```

(`la banque postale` y est déjà ; conserver une seule occurrence.)

- [ ] **Step 5 : Vérifier le succès + non-régression**

Run: `python -m pytest tests/test_extractor.py -q`
Expected: PASS.

- [ ] **Step 6 : Commit**

```bash
git add config.py backend/extractor.py tests/test_extractor.py
git commit -m "feat: suivre La Banque Postale et Crédit Coopératif"
```

---

### Task 3 : Colonnes `statut_temporel` + `date_fermeture_approx` en base

**Files:**
- Modify: `backend/store.py:5-21` (schéma), `backend/store.py:77-105` (`upsert_closure`)
- Test: `tests/test_store.py` (ajouter)

**Interfaces:**
- Produces: table `closures` avec colonnes `statut_temporel TEXT` et `date_fermeture_approx INTEGER` ; `upsert_closure` les écrit (défauts : `"inconnu"`, `0`).

- [ ] **Step 1 : Test d'échec**

```python
# tests/test_store.py (ajout)
from backend import store


def test_closure_persiste_statut_temporel(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, {
        "id": "abc", "banque": "BNP Paribas", "commune": "Lyon",
        "code_insee": None, "departement": "69", "type": "fermeture",
        "date_annonce": None, "date_fermeture": "2025-03-01",
        "statut": "confirmé", "fiabilite": 5, "lat": None, "lon": None,
        "citation": "x", "statut_temporel": "deja_fermee",
        "date_fermeture_approx": 1,
    })
    row = conn.execute(
        "SELECT statut_temporel, date_fermeture_approx FROM closures WHERE id='abc'"
    ).fetchone()
    assert row == ("deja_fermee", 1)
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `python -m pytest tests/test_store.py -q -k statut_temporel`
Expected: FAIL (colonne inexistante).

- [ ] **Step 3 : Ajouter les colonnes au schéma**

Dans `_SCHEMA`, table `closures`, après `citation TEXT,` :

```sql
    statut_temporel TEXT DEFAULT 'inconnu',
    date_fermeture_approx INTEGER DEFAULT 0,
```

- [ ] **Step 4 : Écrire les colonnes dans l'INSERT**

Dans `upsert_closure`, branche INSERT, compléter colonnes et valeurs :

```python
        conn.execute(
            """INSERT INTO closures
            (id, banque, commune, code_insee, departement, type, date_annonce,
             date_fermeture, statut, fiabilite, lat, lon, citation,
             statut_temporel, date_fermeture_approx, created_at)
            VALUES (:id,:banque,:commune,:code_insee,:departement,:type,:date_annonce,
                    :date_fermeture,:statut,:fiabilite,:lat,:lon,:citation,
                    :statut_temporel,:date_fermeture_approx,:created_at)""",
            {
                "statut_temporel": "inconnu",
                "date_fermeture_approx": 0,
                **closure,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
```

(Le `**closure` après les défauts permet d'écraser quand la clé est fournie.)

- [ ] **Step 5 : Vérifier le succès**

Run: `python -m pytest tests/test_store.py -q`
Expected: PASS.

- [ ] **Step 6 : Commit**

```bash
git add backend/store.py tests/test_store.py
git commit -m "feat: persister statut_temporel et date_fermeture_approx"
```

---

### Task 4 : Extracteur — conserver les fermetures passées ≥ plancher

C'est le changement de comportement central. Inverser le rejet du passé et appliquer le plancher.

**Files:**
- Modify: `backend/extractor.py:9-26` (instructions), `:59-70` (`Extraction`), `:137-184` (`extract`)
- Test: `tests/test_extractor.py`

**Interfaces:**
- Consumes: `config.LOOKBACK_MONTHS_DEFAULT`.
- Produces: `extract(article, client, model=..., aujourdhui=None, floor=None) -> Optional[dict]`. Le dict de sortie contient désormais `statut_temporel` et `date_fermeture_approx`. Règles :
  - `a_venir` → conservé (prévisionnel).
  - `deja_fermee` → conservé SI `date_fermeture` connue ET ≥ `floor` ; sinon `None` (→ vigilance).
  - `inconnu` → conservé seulement si `date_fermeture` connue ET ≥ `floor`.

- [ ] **Step 1 : Tests d'échec (comportement temporel)**

```python
# tests/test_extractor.py (ajout)
from datetime import date, timedelta
from backend.extractor import _retenir_fermeture


def test_passee_recente_est_retenue():
    # déjà fermée mais dans la fenêtre -> on garde
    ok = _retenir_fermeture("deja_fermee", "2025-06-01", floor="2025-01-01",
                            aujourdhui="2026-06-25")
    assert ok is True


def test_passee_trop_ancienne_est_rejetee():
    ok = _retenir_fermeture("deja_fermee", "2024-03-01", floor="2025-01-01",
                            aujourdhui="2026-06-25")
    assert ok is False


def test_passee_sans_date_est_rejetee():
    ok = _retenir_fermeture("deja_fermee", None, floor="2025-01-01",
                            aujourdhui="2026-06-25")
    assert ok is False


def test_a_venir_est_retenue_sans_date():
    ok = _retenir_fermeture("a_venir", None, floor="2025-01-01",
                            aujourdhui="2026-06-25")
    assert ok is True
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `python -m pytest tests/test_extractor.py -q -k retenir`
Expected: FAIL (`_retenir_fermeture` n'existe pas).

- [ ] **Step 3 : Implémenter la règle de rétention**

Ajouter dans `extractor.py` (remplace l'ancien `_est_passee`, qui n'est plus utilisé) :

```python
def _retenir_fermeture(statut_temporel: str, date_fermeture: Optional[str],
                       floor: Optional[str], aujourdhui: str) -> bool:
    """True si la fermeture entre dans le périmètre temporel de la veille.

    - a_venir : toujours conservée (prévisionnel), même sans date.
    - deja_fermee / inconnu : conservée seulement si une date effective est
      connue ET >= plancher `floor`. Sans date exploitable -> non conservée
      (le pipeline la routera en vigilance).
    """
    if statut_temporel == "a_venir":
        return True
    if not date_fermeture:
        return False
    try:
        eff = date.fromisoformat(date_fermeture[:10])
    except ValueError:
        return False
    if floor:
        try:
            if eff < date.fromisoformat(floor[:10]):
                return False
        except ValueError:
            pass
    return True
```

- [ ] **Step 4 : Brancher la règle dans `extract` + nouveaux champs**

Mettre à jour la signature et le corps de `extract` :

```python
def extract(article: dict, client, model: str = config.ANTHROPIC_MODEL,
            aujourdhui: Optional[str] = None, floor: Optional[str] = None) -> Optional[dict]:
    aujourdhui = aujourdhui or date.today().isoformat()
    # ... bloc try/except de parse inchangé jusqu'à `data` ...
    if data is None or not data.concerne_banque:
        return None
    if not _retenir_fermeture(data.statut_temporel, data.date_fermeture, floor, aujourdhui):
        return None
    banque = normalise_banque(data.banque)
    if normalise_cle(banque) in getattr(config, "EXCLURE_BANQUES", []):
        return None
    return {
        "id": closure_id(banque, data.commune, data.type),
        "banque": banque,
        "commune": data.commune,
        "code_insee": None,
        "departement": data.departement or article.get("departement"),
        "type": data.type,
        "date_annonce": article.get("date") or None,
        "date_fermeture": data.date_fermeture,
        "statut": data.statut,
        "statut_temporel": data.statut_temporel,
        "date_fermeture_approx": 1 if data.date_fermeture_approx else 0,
        "fiabilite": data.fiabilite,
        "lat": None,
        "lon": None,
        "citation": data.citation,
    }
```

Supprimer les lignes 159-165 d'origine (rejet `deja_fermee` / `_est_passee` / `inconnu`).

- [ ] **Step 5 : Ajouter `date_fermeture_approx` au modèle `Extraction`**

Dans la classe `Extraction`, après `date_fermeture` :

```python
    date_fermeture_approx: bool = Field(
        default=False,
        description="True si la date est approximée depuis une période (ex. 'courant 2025')",
    )
```

- [ ] **Step 6 : Réécrire les instructions du prompt**

Remplacer le bloc `_INSTRUCTIONS` pour autoriser le passé récent et demander une période exploitable :

```python
_INSTRUCTIONS = (
    "Tu analyses un article de presse français. Détermine s'il annonce ou rapporte "
    "la FERMETURE ou la FUSION/REGROUPEMENT d'une agence bancaire physique en France. "
    "Renvoie les informations structurées UNIQUEMENT si l'article nomme une commune "
    "précise d'agence concernée. Sinon concerne_banque=false. "
    "N'invente jamais de commune (pas de région, département, caisse régionale). "
    "On s'intéresse aux fermetures DÉJÀ EFFECTIVES comme À VENIR. Classe statut_temporel : "
    "'a_venir' si la fermeture n'a pas encore eu lieu à la date du jour, 'deja_fermee' si "
    "elle est déjà effective, 'inconnu' sinon. "
    "date_fermeture: date effective ISO YYYY-MM-DD. Si l'article ne donne qu'une PÉRIODE "
    "(ex. 'courant 2025', 'au printemps 2025', 'fin 2025'), renvoie une date approchée "
    "dans cette période et mets date_fermeture_approx=true. Si AUCUNE date ni période "
    "exploitable pour une fermeture déjà effective, laisse date_fermeture vide. "
    "EXCLURE (concerne_banque=false) : fermeture temporaire, travaux, simple suppression "
    "de distributeur (DAB), déménagement dans la MÊME commune, changement d'horaires. "
    "fiabilite: 1 (rumeur vague) à 5 (annonce officielle confirmée). "
    "citation: la phrase exacte qui justifie la fermeture/fusion."
)
```

- [ ] **Step 7 : Vérifier succès + suite extracteur**

Run: `python -m pytest tests/test_extractor.py -q`
Expected: PASS. Corriger les anciens tests qui supposaient le rejet du passé (les adapter au nouveau comportement).

- [ ] **Step 8 : Commit**

```bash
git add backend/extractor.py tests/test_extractor.py
git commit -m "feat: conserver les fermetures effectives depuis le plancher (rétrospectif)"
```

---

### Task 5 : Aligner le fallback OpenAI sur le nouveau schéma

**Files:**
- Modify: `backend/openai_fallback.py:85-108` (`_schema`)
- Test: `tests/test_openai_fallback.py`

**Interfaces:**
- Consumes: `Extraction` (avec `date_fermeture_approx`).
- Produces: `_schema()` inclut `date_fermeture_approx` (boolean) dans `properties` ET `required`.

- [ ] **Step 1 : Test d'échec**

```python
# tests/test_openai_fallback.py (ajout)
from backend.openai_fallback import _schema


def test_schema_inclut_date_approx():
    s = _schema()
    assert "date_fermeture_approx" in s["properties"]
    assert s["properties"]["date_fermeture_approx"] == {"type": "boolean"}
    assert "date_fermeture_approx" in s["required"]
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `python -m pytest tests/test_openai_fallback.py -q -k approx`
Expected: FAIL.

- [ ] **Step 3 : Mettre à jour `_schema`**

Ajouter `"date_fermeture_approx"` à `required` et dans `properties` :

```python
            "date_fermeture_approx": {"type": "boolean"},
```

- [ ] **Step 4 : Vérifier le succès**

Run: `python -m pytest tests/test_openai_fallback.py -q`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add backend/openai_fallback.py tests/test_openai_fallback.py
git commit -m "fix: schéma fallback OpenAI avec date_fermeture_approx"
```

---

### Task 6 : Câbler le plancher `since` dans run.py et l'export

**Files:**
- Modify: `run.py:74-85` (lambda extracteur), `run.py:54` (passer `since` calculé)
- Modify: `backend/export.py:7-9` (`_CLOSURE_COLS`), `:159-192` (CSV)
- Test: `tests/test_export.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `extract(..., floor=since_date)`.
- Produces: `data.json` closures avec clés `statut_temporel`, `date_fermeture_approx` ; CSV avec colonne « Temporalité ».

- [ ] **Step 1 : Test d'échec (export expose le champ)**

```python
# tests/test_export.py (ajout)
from backend import store, export


def test_export_expose_statut_temporel(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, {
        "id": "z", "banque": "La Banque Postale", "commune": "Tulle",
        "code_insee": "19272", "departement": "19", "type": "fermeture",
        "date_annonce": None, "date_fermeture": "2025-09-01", "statut": "confirmé",
        "fiabilite": 4, "lat": 45.2, "lon": 1.7, "citation": "x",
        "statut_temporel": "deja_fermee", "date_fermeture_approx": 0,
    })
    payload = export.build_payload(conn)
    cl = payload["closures"][0]
    assert cl["statut_temporel"] == "deja_fermee"
    assert cl["date_fermeture_approx"] == 0
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `python -m pytest tests/test_export.py -q -k statut_temporel`
Expected: FAIL (clé absente).

- [ ] **Step 3 : Étendre `_CLOSURE_COLS`**

```python
_CLOSURE_COLS = ["id", "banque", "commune", "code_insee", "departement", "type",
                 "date_annonce", "date_fermeture", "statut", "statut_temporel",
                 "date_fermeture_approx", "fiabilite", "lat", "lon", "citation",
                 "created_at"]
```

- [ ] **Step 4 : Ajouter la colonne CSV « Temporalité »**

Dans `export_fermetures_csv`, ajouter `"Temporalité"` à `fields` (après `"Type d'information"`) et dans `writer.writerow` :

```python
                "Temporalité": {"deja_fermee": "Déjà fermée", "a_venir": "À venir"}
                    .get(closure.get("statut_temporel"), "Inconnu"),
```

- [ ] **Step 5 : Passer `floor` à l'extracteur dans run.py**

Dans `main`, calculer le `since` effectif puis :

```python
    recap = run_pipeline(
        conn,
        collectors,
        extractor_fn=lambda art: extract(art, client=client, floor=since_date),
        ...
```

(`since_date` est déjà l'argument de `main`. Comme `_since_from_args` ne renvoie plus `None`, `since_date` est toujours défini.)

- [ ] **Step 6 : Vérifier succès + suite complète**

Run: `python -m pytest -q`
Expected: PASS (corriger les tests d'export/pipeline qui figent l'ancien jeu de colonnes).

- [ ] **Step 7 : Commit**

```bash
git add run.py backend/export.py tests/test_export.py tests/test_pipeline.py
git commit -m "feat: propager le plancher since et exporter la temporalité"
```

---

### Task 7 : Filtre « Période (passée / à venir) » côté frontend

**Files:**
- Modify: `frontend/index.html:46-80` (ajout d'un `<select id="f-temporel">`)
- Modify: `frontend/app.js:124` (liste des filtres), `:383-399` (`filtrer`), `:130-138` (reset)
- Test: `tests/test_frontend_smoke.py`

**Interfaces:**
- Consumes: `closure.statut_temporel`.
- Produces: filtre temporel actif dans `filtrer()`.

- [ ] **Step 1 : Test d'échec (smoke : le select existe)**

```python
# tests/test_frontend_smoke.py (ajout)
from pathlib import Path


def test_filtre_temporel_present():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert 'id="f-temporel"' in html
    js = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "f-temporel" in js
    assert "statut_temporel" in js
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `python -m pytest tests/test_frontend_smoke.py -q -k temporel`
Expected: FAIL.

- [ ] **Step 3 : Ajouter le select dans `index.html`**

Après le bloc `<select id="f-statut">…</select>` :

```html
        <label>Période
          <select id="f-temporel">
            <option value="">Toutes</option>
            <option value="a_venir">À venir</option>
            <option value="deja_fermee">Déjà fermées</option>
          </select>
        </label>
```

- [ ] **Step 4 : Câbler le filtre dans `app.js`**

Ajouter `"f-temporel"` au tableau ligne 124. Dans `filtrer`, après `const statut = val("f-statut");` :

```javascript
  const temporel = val("f-temporel");
```

Et dans le `return DONNEES.closures.filter((c) => { … })`, ajouter la clause :

```javascript
      (!temporel || c.statut_temporel === temporel) &&
```

Dans le reset (ligne ~133), ajouter :

```javascript
    document.getElementById("f-temporel").value = "";
```

- [ ] **Step 5 : Vérifier le succès**

Run: `python -m pytest tests/test_frontend_smoke.py -q`
Expected: PASS.

- [ ] **Step 6 : Commit**

```bash
git add frontend/index.html frontend/app.js tests/test_frontend_smoke.py
git commit -m "feat: filtre période passée/à venir sur la carte"
```

---

### Task 8 : Documentation du nouveau périmètre

**Files:**
- Modify: `README.md:93-138` (section « Sources & limites »), `:36-37`, `:86`

- [ ] **Step 1 : Mettre à jour la doc**

- Périmètre enseignes : retirer « sauf La Banque Postale » ; ajouter La Banque Postale et Crédit Coopératif.
- Fenêtre : indiquer défaut **18 mois glissants** (rétrospectif + prévisionnel), élargissable `--lookback-months 24/30`.
- Préciser que les fermetures **déjà effectives depuis le plancher** sont désormais retenues, et que celles sans date/période exploitable partent en vigilance.

- [ ] **Step 2 : Lancer la suite complète une dernière fois**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 3 : Commit**

```bash
git add README.md
git commit -m "docs: périmètre 18 mois rétrospectif + La Banque Postale"
```

**☑ Checkpoint Phase 1 — livrable autonome : la veille couvre désormais le passé récent + le prévisionnel, La Banque Postale incluse, avec filtre temporel.**

---

# PHASE 2 — Débloquer le rappel (Lot A) : texte intégral + vocabulaire

Vise les deux goulots structurels qui expliquent l'écart avec l'assistant manuel.

### Task 9 : Module `fulltext` — récupérer le corps de l'article

**Files:**
- Create: `backend/fulltext.py`
- Test: `tests/test_fulltext.py`
- Dépendance : ajouter `trafilatura` à `requirements.txt`.

**Interfaces:**
- Produces: `fulltext.fetch_text(url, fetch=None, cache_dir=None) -> str` (chaîne vide si échec ; cache disque par hash d'URL dans `data/cache/fulltext/`).

Conception : `fetch_text` télécharge le HTML (timeout court, User-Agent veille), extrait le contenu via `trafilatura.extract`, met en cache. Tout échec réseau/anti-bot → `""` (best-effort, ne casse pas le run). Test avec un `fetch` injecté renvoyant un HTML fixe + cas d'échec qui lève → `""`.

- [ ] Step 1 : test `test_fetch_text_extrait_le_corps` (HTML injecté → texte attendu)
- [ ] Step 2 : test `test_fetch_text_echec_renvoie_vide` (`fetch` lève → `""`)
- [ ] Step 3 : test `test_fetch_text_utilise_cache` (2e appel ne rappelle pas `fetch`)
- [ ] Step 4 : implémenter `fetch_text` + cache
- [ ] Step 5 : `python -m pytest tests/test_fulltext.py -q` → PASS
- [ ] Step 6 : commit `feat: récupération du texte intégral des articles (best-effort)`

### Task 10 : Enrichir l'article avec le texte intégral avant extraction

**Files:**
- Modify: `backend/pipeline.py:101-110` (entre prefilter et `extractor_fn`)
- Test: `tests/test_pipeline.py`

Conception : après `prefilter.is_relevant` et avant l'appel extracteur, si `art["texte"]` est court (< ~400 car.), compléter `art["texte"]` avec `fulltext.fetch_text(url)` (concaténé, tronqué à ~6000 car. pour le coût IA). Injection de la fonction fetch pour test. Le prefilter reste sur le snippet (rapide), l'IA voit le texte long.

- [ ] Step 1 : test — un article au snippet court est enrichi avant extraction (espion sur la fonction d'enrichissement)
- [ ] Step 2 : vérifier l'échec
- [ ] Step 3 : implémenter l'enrichissement (paramètre `enrich_fn` injectable, défaut `fulltext.fetch_text`)
- [ ] Step 4 : PASS
- [ ] Step 5 : commit `feat: enrichir les articles courts avec le texte intégral`

### Task 11 : Élargir le vocabulaire (prefilter + requêtes + euphémismes)

**Files:**
- Modify: `config.py` (`TERMES_FERMETURE`), `backend/prefilter.py:13` (`_ENSEIGNES_N`), `backend/collectors/google_news.py:11-19` (`_THEMATIQUES`)
- Test: `tests/test_prefilter.py`, `tests/test_google_news.py`

Conception :
1. `TERMES_FERMETURE` += `"rideau"`, `"cesse"`, `"cessation"`, `"rattach"`, `"réorganis"`, `"reorganis"`, `"libre-service"`, `"libre service"`, `"quitte"`, `"quittera"`, `"ferme ses portes"`, `"point de vente"`, `"n'accueillera"`. (Préfixes pour matcher conjugaisons via `in`.)
2. `prefilter._ENSEIGNES_N` doit inclure les **marques régionales** + nouvelles enseignes, pas seulement `config.ENSEIGNES` :

```python
_VARIANTES = config.ENSEIGNES + [
    v for vs in getattr(config, "MARQUES_REGIONALES", {}).values() for v in vs
]
_ENSEIGNES_N = [_normalise(e) for e in _VARIANTES]
```

3. `_THEMATIQUES` (google_news) += quelques requêtes euphémisme : `"banque cesse son activité agence"`, `"agence bancaire transférée"`, `"réorganisation réseau bancaire agence"`.

- [ ] Step 1 : test prefilter — « La Banque Kolb baisse le rideau à X » devient pertinent (enseigne régionale + euphémisme « rideau »)
- [ ] Step 2 : test prefilter — euphémisme « cesse son activité » + enseigne nationale → pertinent
- [ ] Step 3 : vérifier l'échec
- [ ] Step 4 : implémenter (config + prefilter + google_news)
- [ ] Step 5 : `python -m pytest tests/test_prefilter.py tests/test_google_news.py -q` → PASS
- [ ] Step 6 : commit `feat: élargir vocabulaire et marques régionales au prefilter`

---

# PHASE 3 — Étendre la couverture (Lot B)

### Task 12 : Découpage mensuel des requêtes denses (battre le plafond ~100)

**Files:** `backend/collectors/google_news.py` (`_feed_url`, `collect`), `tests/test_google_news.py`.
Conception : pour les requêtes à fort volume (thématiques + CA/SG/BNP national), générer une requête par tranche mensuelle via les opérateurs Google News `after:YYYY-MM-DD before:YYYY-MM-DD` couvrant `[since, today]`, au lieu d'un seul `when:`. Garder `when:` pour les requêtes longue traîne (département, marques). Dédup par URL déjà en place. Paramétrer le set « dense » pour limiter le volume d'appels.

- [ ] Tests : génération des tranches mensuelles entre deux dates ; une requête dense produit N feeds.
- [ ] Implémentation + commit `feat: découpage mensuel des requêtes Google News denses`

### Task 13 : Passe descendante commune par commune

**Files:** nouveau `backend/drilldown.py`, intégration `run.py`, `tests/test_drilldown.py`.
Conception : quand l'IA renvoie un article « plan départemental » (plusieurs communes citées / volume > 1), extraire la liste des communes nommées et générer des requêtes `"{banque}" "{commune}" fermeture` réinjectées dans un 2e tour de collecte Google News. Plafonner (ex. 5 communes/article, budget global) pour le coût. L'extracteur tourne sur ces nouveaux articles comme les autres.

- [ ] Tests : extraction des communes d'un texte de plan ; génération des requêtes ciblées.
- [ ] Implémentation + commit `feat: drill-down commune depuis les plans départementaux`

### Task 14 : Collecteur web complémentaire (hors Google News RSS)

**Files:** nouveau `backend/collectors/web_search.py`, `tests/test_web_search.py`.
Conception : collecteur best-effort via un moteur web (SerpAPI ou Bing News API selon clé dispo `WEB_SEARCH_API_KEY`) sur les requêtes `site:` PQR + euphémismes. Sans clé → `[]` (même contrat que `presse_pro`/`legifrance`). Réutilise le pipeline et `fulltext`.

- [ ] Tests : sans clé → `[]` ; avec réponse injectée → articles normalisés `{titre,texte,url,date,source}`.
- [ ] Implémentation + ajout dans `run.collectors` + commit `feat: collecteur web complémentaire (best-effort)`

---

# PHASE 4 — Fiabilité & hygiène (Lot C)

### Task 15 : Hiérarchie de sources A→E par domaine

**Files:** nouveau `backend/source_tier.py`, intégration `export.py`, `tests/test_source_tier.py`.
Conception : `tier(url) -> "A"|"B"|"C"|"D"|"E"` par mapping domaine (communiqué banque/mairie = A ; PQR identifiée = B ; france3/ici/actu.fr = C ; reste presse = D ; réseaux/annuaires = E). Exposé par source dans `data.json` à côté de `fiabilite`.

- [ ] Tests par domaine ; intégration export ; commit `feat: hiérarchie de sources A-E`

### Task 16 : Clé d'événement enrichie + normalisation banque robuste

**Files:** `backend/dedup.py` (`closure_id`), `backend/extractor.py` (normalisation), `tests/test_dedup.py`.
Conception :
- `closure_id` inclut un composant **adresse/quartier** quand disponible (sinon retombe sur banque|commune|type) pour éviter de fusionner deux agences distinctes d'une même banque/commune.
- Rejeter les fermetures sans banque canonique (corrige `BNP-Paribas`, banque vide vus dans `data.json`). Normaliser `BNP Paribas` (tiret/espace).

- [ ] Tests : `BNP-Paribas` → `BNP Paribas` ; banque vide → rejet ; deux adresses même commune → 2 ids.
- [ ] Implémentation + commit `fix: clé d'événement avec adresse + normalisation banque stricte`

---

## Self-Review (couverture spec)

- Rétrospectif depuis ~2025 → Tasks 1, 4, 6 ✅
- Fenêtre 18 mois élargissable → Task 1 (+ `--lookback-months` déjà présent dans `run.py`) ✅
- Mise à jour basée sur la date actuelle → fin de fenêtre = `date.today()` (Task 1) ; `generated_at` déjà en `now(UTC)` (`export.py:83`) ✅
- La Banque Postale + Crédit Coopératif → Task 2 ✅
- Affichage passé vs à venir → Tasks 3, 6, 7 ✅
- Goulots de rappel (texte intégral, vocabulaire, marques régionales, drill-down) → Tasks 9-13 ✅
- Fiabilité / dédup / exclusions → prompt Task 4 (exclusions) + Tasks 15-16 ✅

Décisions encore ouvertes pour Phases 3-4 (à trancher au moment d'exécuter ces tâches) : choix du moteur web (SerpAPI vs Bing) en Task 14 ; granularité du composant adresse dans la clé en Task 16. Les Phases 2-4 sont à éclater en steps niveau-action avant exécution.
