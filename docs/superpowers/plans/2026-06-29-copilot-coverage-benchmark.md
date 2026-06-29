# Benchmark Copilot (Cycle 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire `tools/compare_copilot_coverage.py`, un comparateur read-only qui classe chaque ligne du fichier de référence Copilot sur deux axes (couverture dans notre base + fiabilité de la source) et produit un rapport CSV/JSON sans qu'aucune ligne ne reste inexpliquée.

**Architecture:** Un module CLI unique qui (1) charge l'Excel Copilot par mapping positionnel, (2) charge `data/export/data.json` + `tools/copilot_overrides.json`, (3) classe la couverture (closures → carte/unlocated ; vigilances/estimations → département ; sinon needs_research), (4) applique l'axe fiabilité depuis les overrides + une heuristique URL, (5) assemble un enregistrement par ligne en garantissant l'invariant, (6) écrit CSV+JSON et un récap console. Réutilise les helpers de normalisation existants. **Aucune écriture pipeline, aucune recherche web, aucune création de closure.**

**Tech Stack:** Python 3.12, openpyxl, json/csv stdlib, pytest. Réutilise `backend.dedup`, `backend.extractor`, `backend.drilldown`, `config`, et `tools.compare_expected_closures`.

## Global Constraints

- **Interpréteur : `python3.12`** uniquement (le dépôt utilise la syntaxe `str | Path` ; `python3` système = 3.9.6 et échoue à importer `config`). Toutes les commandes pytest/CLI utilisent `python3.12`.
- **Read-only Cycle 1** : ne modifie pas le pipeline, ne crée pas de closures, ne lance aucune recherche web. Lecture seule de l'Excel + `data.json` + overrides ; écriture seulement de `data/export/copilot_coverage.{csv,json}`.
- **Pas de nouvelle dépendance** : overrides en JSON (pas de PyYAML).
- **Invariant** : chaque enregistrement émis a `status` ∈ {present_on_map, present_unlocated, present_department, needs_research, rejected_with_reason, confirmed_missing}, un `next_action` non vide, et un `source_reliability` ∈ {high, medium, low}. Aucune ligne inexpliquée.
- **Tests via fixtures** : les tests pytest génèrent une fixture xlsx minimale (openpyxl) ; ils ne dépendent jamais de l'Excel réel. La validation sur l'Excel réel est une étape CLI manuelle (Task 6).
- **Libellés vérifiés** : Reuilly → `Crédit Agricole Centre Ouest` ; Pleudihen-sur-Rance → `Crédit Mutuel de Bretagne`.

---

## Structure des fichiers

- **Create** `tools/compare_copilot_coverage.py` — module CLI complet (loaders, classification, fiabilité, assemblage, writers, main).
- **Create** `tests/test_compare_copilot_coverage.py` — fixtures + tests TDD.
- **Use as-is** `tools/copilot_overrides.json` — déjà committé (6 règles auditées).
- **Reuse (no change)** `backend/dedup.py` (`normalise_cle`), `backend/extractor.py` (`normalise_banque`), `backend/drilldown.py` (`est_plan`), `config.py` (`DEPARTEMENTS`), `tools/compare_expected_closures.py` (`_cle_banque`, `_cle_commune`).

Mapping positionnel des colonnes de l'Excel (constante du module) :

| idx | champ interne |
|---|---|
| 0 | banque (en-tête littéral `²`) |
| 1 | agence_localisation |
| 2 | adresse |
| 3 | commune |
| 4 | departement (nom) |
| 5 | region |
| 6 | lat |
| 7 | lon |
| 8 | date_fermeture |
| 9 | precision_date |
| 10 | source |
| 11 | url |
| 14 | score |
| 15 | statut_copilot |
| 16 | commentaires |

---

### Task 1: Chargement de l'Excel Copilot

**Files:**
- Create: `tools/compare_copilot_coverage.py`
- Test: `tests/test_compare_copilot_coverage.py`

**Interfaces:**
- Produces: `COPILOT_COLS: dict[str,int]` ; `load_copilot_rows(path: str | Path) -> list[dict]` renvoyant des dicts aux clés : `banque, agence_localisation, adresse, commune, departement, region, lat, lon, date_fermeture, precision_date, source, url, score, statut_copilot, commentaires`. Valeurs : chaînes nettoyées (`str.strip()`), sauf `lat`/`lon` qui restent la valeur brute (float ou "").

- [ ] **Step 1: Écrire le test qui échoue (loader + fixture xlsx)**

```python
# tests/test_compare_copilot_coverage.py
from pathlib import Path

from openpyxl import Workbook

from tools.compare_copilot_coverage import load_copilot_rows


def _make_xlsx(path: Path, rows: list[list]) -> Path:
    """Écrit un xlsx avec l'en-tête réel de l'Excel Copilot puis les lignes données."""
    wb = Workbook()
    ws = wb.active
    header = ["²", "Agence / localisation", "Adresse la plus complète possible",
              "Commune", "Département", "Région", "Latitude", "Longitude",
              "Date de fermeture", "Précision date", "Source principale",
              "Lien source", "Sources de localisation", "Lien localisation",
              "Score confiance", "Statut", "Commentaires"]
    ws.append(header)
    for r in rows:
        ws.append(r + [""] * (len(header) - len(r)))
    wb.save(path)
    return path


def test_load_copilot_rows_maps_columns(tmp_path):
    path = _make_xlsx(tmp_path / "ref.xlsx", [
        ["BNP Paribas", "Chalon - av. de Paris", "141 avenue de Paris, 71100 Chalon",
         "Chalon-sur-Saône", "Saône-et-Loire", "BFC", 46.79, 4.84,
         "2026-06-30", "exacte", "Fichier principal V2", "", "", "", 96, "Confirmé", "note"],
    ])
    rows = load_copilot_rows(path)
    assert len(rows) == 1
    r = rows[0]
    assert r["banque"] == "BNP Paribas"
    assert r["commune"] == "Chalon-sur-Saône"
    assert r["departement"] == "Saône-et-Loire"
    assert r["source"] == "Fichier principal V2"
    assert r["url"] == ""
    assert r["score"] == "96"
    assert float(r["lat"]) == 46.79


def test_load_copilot_rows_skips_blank_rows(tmp_path):
    path = _make_xlsx(tmp_path / "ref.xlsx", [
        ["BNP Paribas", "", "", "Lyon", "Rhône", "", "", "", "", "", "V2", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ])
    rows = load_copilot_rows(path)
    assert len(rows) == 1
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -v`
Expected: FAIL avec `ImportError`/`ModuleNotFoundError` (le module n'existe pas).

- [ ] **Step 3: Écrire l'implémentation minimale**

```python
# tools/compare_copilot_coverage.py
"""Benchmark de couverture Copilot (Cycle 1, read-only).

Classe chaque ligne du fichier de référence Copilot sur deux axes :
  - couverture dans notre base (data.json) : present_on_map / present_unlocated /
    present_department / needs_research / rejected_with_reason / confirmed_missing ;
  - fiabilité de la source Copilot : high / medium / low (+ source_flag).

Ne modifie jamais le pipeline. Produit data/export/copilot_coverage.{csv,json}.
"""
from __future__ import annotations

from pathlib import Path

# Mapping positionnel des colonnes de l'Excel Copilot (en-tête banque = "²").
COPILOT_COLS: dict[str, int] = {
    "banque": 0, "agence_localisation": 1, "adresse": 2, "commune": 3,
    "departement": 4, "region": 5, "lat": 6, "lon": 7, "date_fermeture": 8,
    "precision_date": 9, "source": 10, "url": 11, "score": 14,
    "statut_copilot": 15, "commentaires": 16,
}
_RAW_COLS = {"lat", "lon"}  # conservés bruts (float), pas de .strip()


def _cell(values, idx):
    return values[idx] if idx < len(values) else None


def load_copilot_rows(path) -> list[dict]:
    """Charge l'Excel Copilot en liste de dicts (mapping positionnel)."""
    from openpyxl import load_workbook

    wb = load_workbook(Path(path), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    next(rows_iter, None)  # saute l'en-tête
    out: list[dict] = []
    for values in rows_iter:
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            continue
        row: dict = {}
        for champ, idx in COPILOT_COLS.items():
            v = _cell(values, idx)
            if champ in _RAW_COLS:
                row[champ] = v if v is not None else ""
            else:
                row[champ] = "" if v is None else str(v).strip()
        out.append(row)
    return out
```

- [ ] **Step 4: Lancer le test pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/compare_copilot_coverage.py tests/test_compare_copilot_coverage.py
git commit -m "feat(copilot): chargement positionnel de l'Excel de référence"
```

---

### Task 2: Helpers de normalisation, table dept nom→code, chargement des overrides

**Files:**
- Modify: `tools/compare_copilot_coverage.py`
- Test: `tests/test_compare_copilot_coverage.py`

**Interfaces:**
- Consumes: `tools.compare_expected_closures._cle_banque`, `_cle_commune` ; `backend.dedup.normalise_cle` ; `config.DEPARTEMENTS`.
- Produces : `dept_name_to_code(name: str | None) -> str | None` ; `load_overrides(path: str | Path | None) -> dict` (renvoie `{"sources": [...], "rows": [...]}`, sections absentes → listes vides, fichier absent → `{"sources": [], "rows": []}`).

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_compare_copilot_coverage.py (ajouter)
import json

from tools.compare_copilot_coverage import dept_name_to_code, load_overrides


def test_dept_name_to_code():
    assert dept_name_to_code("Indre-et-Loire") == "37"
    assert dept_name_to_code("saône-et-loire") == "71"  # insensible casse/accents
    assert dept_name_to_code("Pays Imaginaire") is None
    assert dept_name_to_code("") is None


def test_load_overrides_missing_file_returns_empty():
    ov = load_overrides(None)
    assert ov == {"sources": [], "rows": []}


def test_load_overrides_reads_sections(tmp_path):
    p = tmp_path / "ov.json"
    p.write_text(json.dumps({"sources": [{"match_source": "moneyvox"}]}), encoding="utf-8")
    ov = load_overrides(p)
    assert ov["sources"] == [{"match_source": "moneyvox"}]
    assert ov["rows"] == []
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -k "dept_name or overrides" -v`
Expected: FAIL avec `ImportError` (`dept_name_to_code`/`load_overrides` non définis).

- [ ] **Step 3: Écrire l'implémentation**

```python
# tools/compare_copilot_coverage.py (ajouter en haut, après les imports existants)
import json

from backend.dedup import normalise_cle
from tools.compare_expected_closures import _cle_banque, _cle_commune
import config

# Table inverse {nom normalisé du département -> code}.
_DEPT_NAME_TO_CODE = {normalise_cle(nom): code for code, nom in config.DEPARTEMENTS.items()}


def _norm(s) -> str:
    return normalise_cle(s or "")


def dept_name_to_code(name) -> str | None:
    return _DEPT_NAME_TO_CODE.get(normalise_cle(name or "")) or None


def load_overrides(path) -> dict:
    """Charge tools/copilot_overrides.json. Fichier absent/None -> sections vides."""
    if not path or not Path(path).exists():
        return {"sources": [], "rows": []}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"sources": data.get("sources") or [], "rows": data.get("rows") or []}
```

- [ ] **Step 4: Lancer le test pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -v`
Expected: PASS (tous les tests, y compris ceux de la Task 1).

- [ ] **Step 5: Commit**

```bash
git add tools/compare_copilot_coverage.py tests/test_compare_copilot_coverage.py
git commit -m "feat(copilot): helpers normalisation, dept nom->code, chargement overrides"
```

---

### Task 3: Classification de couverture

**Files:**
- Modify: `tools/compare_copilot_coverage.py`
- Test: `tests/test_compare_copilot_coverage.py`

**Interfaces:**
- Produces : `classify_coverage(row: dict, payload: dict) -> dict` renvoyant `{"status": str, "match_type": str, "pipeline_id": str, "pipeline_status": str}`. `status` ∈ {present_on_map, present_unlocated, present_department, needs_research}. `match_type` ∈ {exact, commune, département, aucun}.

Règles :
1. Closure (même banque ; commune == `commune`/`agence_localisation`/`commune_originale`) **avec lat+lon** → `present_on_map` ; `match_type=exact` si haversine(point Copilot, point closure) < 500 m, sinon `commune`.
2. Même match **sans lat/lon** → `present_unlocated`, `match_type=commune`.
3. Sinon, signal département pour (banque, code dept) — vigilance `departement==code` & banque, ou `department_estimates[code].signals[].banque` — → `present_department`, `match_type=département`.
4. Sinon → `needs_research`, `match_type=aucun`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_compare_copilot_coverage.py (ajouter)
from tools.compare_copilot_coverage import classify_coverage


def _row(banque="BNP Paribas", commune="Lyon", departement="Rhône", lat="", lon="",
         agence_localisation="", source="V2", url=""):
    return {"banque": banque, "commune": commune, "departement": departement,
            "lat": lat, "lon": lon, "agence_localisation": agence_localisation,
            "commune_originale": "", "source": source, "url": url,
            "statut_copilot": "", "commentaires": "", "score": ""}


def test_present_on_map_exact_via_geo():
    payload = {"closures": [{"id": "abc", "banque": "BNP Paribas", "commune": "Lyon",
                             "lat": 45.75, "lon": 4.85, "statut": "confirmé"}]}
    cov = classify_coverage(_row(commune="Lyon", lat=45.751, lon=4.851), payload)
    assert cov["status"] == "present_on_map"
    assert cov["match_type"] == "exact"
    assert cov["pipeline_id"] == "abc"
    assert cov["pipeline_status"] == "confirmé"


def test_present_on_map_commune_when_geo_far():
    payload = {"closures": [{"id": "abc", "banque": "BNP Paribas", "commune": "Lyon",
                             "lat": 45.75, "lon": 4.85}]}
    cov = classify_coverage(_row(commune="Lyon", lat=48.85, lon=2.35), payload)
    assert cov["status"] == "present_on_map"
    assert cov["match_type"] == "commune"


def test_present_unlocated_when_closure_has_no_geo():
    payload = {"closures": [{"id": "abc", "banque": "BNP Paribas", "commune": "Lyon",
                             "lat": None, "lon": None}]}
    cov = classify_coverage(_row(commune="Lyon"), payload)
    assert cov["status"] == "present_unlocated"
    assert cov["match_type"] == "commune"


def test_present_department_via_vigilance():
    payload = {"closures": [],
               "vigilances": [{"banque": "BNP Paribas", "departement": "69"}]}
    cov = classify_coverage(_row(commune="Lyon", departement="Rhône"), payload)
    assert cov["status"] == "present_department"
    assert cov["match_type"] == "département"


def test_needs_research_when_nothing_matches():
    cov = classify_coverage(_row(commune="Lyon", departement="Rhône"), {"closures": []})
    assert cov["status"] == "needs_research"
    assert cov["match_type"] == "aucun"
    assert cov["pipeline_id"] == ""
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -k coverage -v`
Expected: FAIL avec `ImportError` (`classify_coverage` non défini).

- [ ] **Step 3: Écrire l'implémentation**

```python
# tools/compare_copilot_coverage.py (ajouter)
import math


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _row_matches_closure(banque_cle: str, commune_cle: str, cl: dict) -> bool:
    if not commune_cle or _cle_banque(cl.get("banque")) != banque_cle:
        return False
    for champ in ("commune", "agence_localisation", "commune_originale"):
        if _cle_commune(cl.get(champ)) == commune_cle:
            return True
    return False


def _as_float(v):
    try:
        if v in (None, ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _has_department_signal(banque_cle: str, dept_code: str, payload: dict) -> bool:
    for v in payload.get("vigilances") or []:
        if v.get("departement") == dept_code and _cle_banque(v.get("banque")) == banque_cle:
            return True
    est = (payload.get("department_estimates") or {}).get(dept_code)
    if est:
        for sig in est.get("signals") or []:
            if _cle_banque(sig.get("banque")) == banque_cle:
                return True
    return False


def classify_coverage(row: dict, payload: dict) -> dict:
    banque_cle = _cle_banque(row.get("banque"))
    commune_cle = _cle_commune(row.get("commune"))
    for cl in payload.get("closures") or []:
        if not _row_matches_closure(banque_cle, commune_cle, cl):
            continue
        cl_lat, cl_lon = _as_float(cl.get("lat")), _as_float(cl.get("lon"))
        has_geo = cl_lat is not None and cl_lon is not None
        if not has_geo:
            return {"status": "present_unlocated", "match_type": "commune",
                    "pipeline_id": cl.get("id", ""),
                    "pipeline_status": cl.get("statut") or cl.get("statut_temporel") or ""}
        match_type = "commune"
        row_lat, row_lon = _as_float(row.get("lat")), _as_float(row.get("lon"))
        if row_lat is not None and row_lon is not None:
            if _haversine_m(row_lat, row_lon, cl_lat, cl_lon) < 500:
                match_type = "exact"
        return {"status": "present_on_map", "match_type": match_type,
                "pipeline_id": cl.get("id", ""),
                "pipeline_status": cl.get("statut") or cl.get("statut_temporel") or ""}

    dept_code = dept_name_to_code(row.get("departement"))
    if dept_code and _has_department_signal(banque_cle, dept_code, payload):
        return {"status": "present_department", "match_type": "département",
                "pipeline_id": "", "pipeline_status": ""}
    return {"status": "needs_research", "match_type": "aucun",
            "pipeline_id": "", "pipeline_status": ""}
```

- [ ] **Step 4: Lancer le test pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -v`
Expected: PASS (tous).

- [ ] **Step 5: Commit**

```bash
git add tools/compare_copilot_coverage.py tests/test_compare_copilot_coverage.py
git commit -m "feat(copilot): classification de couverture (carte/unlocated/dept/needs_research)"
```

---

### Task 4: Axe fiabilité (overrides source + ligne + heuristique URL)

**Files:**
- Modify: `tools/compare_copilot_coverage.py`
- Test: `tests/test_compare_copilot_coverage.py`

**Interfaces:**
- Produces : `apply_reliability(row: dict, overrides: dict) -> dict`. Clés possibles : `source_reliability` (toujours présent, high/medium/low), `source_flag`, `status`, `missing_reason`, `next_action`, `_source_default_status`, `_source_default_next_action`. Les règles `rows` priment sur les règles `sources`. Heuristique par défaut si aucune fiabilité fixée : `medium` si URL présente, sinon `low`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_compare_copilot_coverage.py (ajouter)
from tools.compare_copilot_coverage import apply_reliability

_OV = {
    "sources": [
        {"match_source": "moneyvox", "source_reliability": "medium",
         "source_flag": "article_list_secondary"},
        {"match_source": "fichier principal v2", "require_no_url": True,
         "source_reliability": "low", "source_flag": "inherited_source_to_trace",
         "default_status_if_uncovered": "needs_research",
         "default_next_action": "Tracer la source primaire."},
    ],
    "rows": [
        {"match": {"banque": "Crédit Agricole Centre Ouest", "commune": "Reuilly"},
         "source_reliability": "high", "source_flag": "confirmed"},
    ],
}


def test_reliability_source_rule_moneyvox():
    rel = apply_reliability(_row(source="MoneyVox, 06/06/2025", url="http://x"), _OV)
    assert rel["source_reliability"] == "medium"
    assert rel["source_flag"] == "article_list_secondary"


def test_reliability_v2_requires_no_url():
    rel = apply_reliability(_row(source="Fichier principal V2", url=""), _OV)
    assert rel["source_reliability"] == "low"
    assert rel["source_flag"] == "inherited_source_to_trace"
    assert rel["_source_default_status"] == "needs_research"
    # Une ligne V2 AVEC une url ne déclenche pas la règle (require_no_url).
    rel2 = apply_reliability(_row(source="Fichier principal V2", url="http://x"), _OV)
    assert rel2["source_reliability"] == "medium"  # heuristique URL présente
    assert rel2.get("source_flag") in (None, "")


def test_reliability_row_rule_reuilly():
    rel = apply_reliability(
        _row(banque="Crédit Agricole Centre Ouest", commune="Reuilly",
             source="ICI Centre-Val de Loire", url="http://x"), _OV)
    assert rel["source_reliability"] == "high"
    assert rel["source_flag"] == "confirmed"


def test_reliability_default_heuristic():
    assert apply_reliability(_row(source="Inconnu", url="http://x"), _OV)["source_reliability"] == "medium"
    assert apply_reliability(_row(source="Inconnu", url=""), _OV)["source_reliability"] == "low"
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -k reliability -v`
Expected: FAIL avec `ImportError` (`apply_reliability` non défini).

- [ ] **Step 3: Écrire l'implémentation**

```python
# tools/compare_copilot_coverage.py (ajouter)
_ROW_OVERRIDE_FIELDS = ("status", "missing_reason", "next_action",
                        "source_reliability", "source_flag")


def apply_reliability(row: dict, overrides: dict) -> dict:
    result: dict = {}
    src = _norm(row.get("source"))
    has_url = bool((row.get("url") or "").strip())

    # 1. Règles par motif de source.
    for rule in overrides.get("sources") or []:
        if _norm(rule.get("match_source")) not in src:
            continue
        if rule.get("require_no_url") and has_url:
            continue
        for k in ("source_reliability", "source_flag"):
            if rule.get(k):
                result[k] = rule[k]
        if rule.get("default_status_if_uncovered"):
            result["_source_default_status"] = rule["default_status_if_uncovered"]
        if rule.get("default_next_action"):
            result["_source_default_next_action"] = rule["default_next_action"]

    # 2. Règles par ligne (priment sur les règles de source).
    banque_cle = _cle_banque(row.get("banque"))
    commune_cle = _cle_commune(row.get("commune"))
    for rule in overrides.get("rows") or []:
        m = rule.get("match") or {}
        if _cle_banque(m.get("banque")) != banque_cle or _cle_commune(m.get("commune")) != commune_cle:
            continue
        al = m.get("agence_localisation")
        if al and _cle_commune(al) != _cle_commune(row.get("agence_localisation")):
            continue
        for k in _ROW_OVERRIDE_FIELDS:
            if rule.get(k) is not None:
                result[k] = rule[k]

    # 3. Heuristique de fiabilité par défaut.
    if not result.get("source_reliability"):
        result["source_reliability"] = "medium" if has_url else "low"
    return result
```

- [ ] **Step 4: Lancer le test pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -v`
Expected: PASS (tous).

- [ ] **Step 5: Commit**

```bash
git add tools/compare_copilot_coverage.py tests/test_compare_copilot_coverage.py
git commit -m "feat(copilot): axe fiabilité (overrides source/ligne + heuristique URL)"
```

---

### Task 5: Assemblage de l'enregistrement + next_action + invariant

**Files:**
- Modify: `tools/compare_copilot_coverage.py`
- Test: `tests/test_compare_copilot_coverage.py`

**Interfaces:**
- Produces : `RECORD_FIELDS: list[str]` (ordre des colonnes de sortie) ; `default_next_action_queries(row: dict) -> str` ; `build_record(row: dict, payload: dict, overrides: dict) -> dict`. `build_record` garantit l'invariant (status/next_action/source_reliability non vides). `matched_pipeline` = "oui" si `match_type != "aucun"` sinon "non".

Logique de combinaison :
- `status` = override `status` de ligne si présent, sinon : si couverture `needs_research` ET règle source a `default_status_if_uncovered`, on l'utilise ; sinon la couverture auto.
- `next_action` = override `next_action` (ligne) si présent ; sinon `_source_default_next_action` ; sinon dérivé du `status` (requêtes pour needs_research ; messages fixes sinon).

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_compare_copilot_coverage.py (ajouter)
from tools.compare_copilot_coverage import (
    build_record, default_next_action_queries, RECORD_FIELDS, COVERAGE_STATUSES,
)


def test_next_action_queries_non_empty():
    q = default_next_action_queries(_row(banque="BNP Paribas", commune="Lyon"))
    assert "BNP Paribas" in q and "Lyon" in q and "fermeture agence" in q


def test_build_record_invariant_always_filled():
    rec = build_record(_row(commune="Nowhere", source="Inconnu", url=""), {"closures": []}, {"sources": [], "rows": []})
    assert rec["status"] in COVERAGE_STATUSES
    assert rec["next_action"].strip() != ""
    assert rec["source_reliability"] in {"high", "medium", "low"}
    assert set(RECORD_FIELDS).issubset(rec.keys())


def test_build_record_present_on_map_matched_oui():
    payload = {"closures": [{"id": "abc", "banque": "BNP Paribas", "commune": "Lyon",
                             "lat": 45.75, "lon": 4.85, "statut": "confirmé"}]}
    rec = build_record(_row(commune="Lyon", lat=45.751, lon=4.851), payload, {"sources": [], "rows": []})
    assert rec["status"] == "present_on_map"
    assert rec["matched_pipeline"] == "oui"
    assert rec["pipeline_id"] == "abc"


def test_build_record_v2_uncovered_uses_source_default_status():
    ov = {"sources": [{"match_source": "fichier principal v2", "require_no_url": True,
                       "source_reliability": "low", "source_flag": "inherited_source_to_trace",
                       "default_status_if_uncovered": "needs_research",
                       "default_next_action": "Tracer la source primaire."}], "rows": []}
    rec = build_record(_row(commune="Nulpart", source="Fichier principal V2", url=""), {"closures": []}, ov)
    assert rec["status"] == "needs_research"
    assert rec["source_flag"] == "inherited_source_to_trace"
    assert rec["next_action"] == "Tracer la source primaire."


def test_build_record_row_override_forces_rejected():
    ov = {"sources": [], "rows": [
        {"match": {"banque": "BNP Paribas", "commune": "Lyon"},
         "status": "rejected_with_reason", "missing_reason": "hors périmètre",
         "source_reliability": "low"}]}
    rec = build_record(_row(commune="Lyon", source="x", url=""), {"closures": []}, ov)
    assert rec["status"] == "rejected_with_reason"
    assert rec["missing_reason"] == "hors périmètre"
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -k "build_record or next_action" -v`
Expected: FAIL avec `ImportError`.

- [ ] **Step 3: Écrire l'implémentation**

```python
# tools/compare_copilot_coverage.py (ajouter)
from backend.drilldown import est_plan

COVERAGE_STATUSES = ["present_on_map", "present_unlocated", "present_department",
                     "needs_research", "rejected_with_reason", "confirmed_missing"]

RECORD_FIELDS = [
    "banque", "agence_localisation", "commune", "departement", "adresse",
    "lat", "lon", "source", "url", "score_copilot", "statut_copilot",
    "matched_pipeline", "match_type", "pipeline_id", "pipeline_status",
    "status", "missing_reason", "next_action", "source_reliability", "source_flag",
]

_NEXT_ACTION_BY_STATUS = {
    "present_on_map": "Aucune — déjà sur la carte ; contrôler la fiabilité de la source.",
    "present_unlocated": "Géocoder à l'adresse précise pour publication carte.",
    "present_department": "Identifier l'agence/commune précise pour faire monter le signal départemental.",
    "rejected_with_reason": "Voir missing_reason ; ne pas publier.",
    "confirmed_missing": "Voir missing_reason ; intégrer si une source fiable est retrouvée.",
}


def default_next_action_queries(row: dict) -> str:
    banque, commune = row.get("banque", ""), row.get("commune", "")
    requetes = [
        f'"{banque}" "{commune}" "fermeture agence"',
        f'"{banque}" "{commune}" "agence ferme"',
        f'"{banque}" "{commune}" "regroupement agence"',
        f'"{commune}" "banque ferme"',
    ]
    contexte = " ".join(filter(None, [row.get("agence_localisation"),
                                      row.get("statut_copilot"), row.get("commentaires")]))
    if est_plan(contexte):
        requetes.append(f'"{banque}" "plan" "fermeture" "agences"')
    return " | ".join(requetes[:5])


def build_record(row: dict, payload: dict, overrides: dict) -> dict:
    cov = classify_coverage(row, payload)
    rel = apply_reliability(row, overrides)

    status = rel.get("status")
    if not status:
        if cov["status"] == "needs_research" and rel.get("_source_default_status"):
            status = rel["_source_default_status"]
        else:
            status = cov["status"]

    next_action = rel.get("next_action") or rel.get("_source_default_next_action")
    if not next_action:
        next_action = (default_next_action_queries(row) if status == "needs_research"
                       else _NEXT_ACTION_BY_STATUS.get(status, "À qualifier."))

    return {
        "banque": row.get("banque", ""),
        "agence_localisation": row.get("agence_localisation", ""),
        "commune": row.get("commune", ""),
        "departement": row.get("departement", ""),
        "adresse": row.get("adresse", ""),
        "lat": row.get("lat", ""),
        "lon": row.get("lon", ""),
        "source": row.get("source", ""),
        "url": row.get("url", ""),
        "score_copilot": row.get("score", ""),
        "statut_copilot": row.get("statut_copilot", ""),
        "matched_pipeline": "oui" if cov["match_type"] != "aucun" else "non",
        "match_type": cov["match_type"],
        "pipeline_id": cov["pipeline_id"],
        "pipeline_status": cov["pipeline_status"],
        "status": status,
        "missing_reason": rel.get("missing_reason", ""),
        "next_action": next_action,
        "source_reliability": rel["source_reliability"],
        "source_flag": rel.get("source_flag", ""),
    }
```

- [ ] **Step 4: Lancer le test pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -v`
Expected: PASS (tous).

- [ ] **Step 5: Commit**

```bash
git add tools/compare_copilot_coverage.py tests/test_compare_copilot_coverage.py
git commit -m "feat(copilot): assemblage enregistrement + next_action + invariant"
```

---

### Task 6: Writers CSV/JSON, récap, CLI, et vérification sur l'Excel réel

**Files:**
- Modify: `tools/compare_copilot_coverage.py`
- Test: `tests/test_compare_copilot_coverage.py`

**Interfaces:**
- Produces : `compare(rows, payload, overrides) -> list[dict]` ; `summarize(records) -> dict` ; `write_csv(records, path)` ; `write_json(records, summary, path)` ; `main(argv=None) -> int`.
- CLI : `python3.12 -m tools.compare_copilot_coverage <ref.xlsx> [--payload data/export/data.json] [--overrides tools/copilot_overrides.json] [--out-dir data/export]`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_compare_copilot_coverage.py (ajouter)
import csv as _csv

from tools.compare_copilot_coverage import compare, summarize, write_csv, write_json, main


def test_compare_and_summarize():
    rows = [_row(commune="Lyon"), _row(commune="Nulpart")]
    payload = {"closures": [{"id": "abc", "banque": "BNP Paribas", "commune": "Lyon",
                             "lat": 45.75, "lon": 4.85}]}
    recs = compare(rows, payload, {"sources": [], "rows": []})
    assert len(recs) == 2
    summ = summarize(recs)
    assert summ["present_on_map"] == 1
    assert summ["needs_research"] == 1


def test_write_csv_json_have_all_columns(tmp_path):
    recs = compare([_row(commune="Lyon")], {"closures": []}, {"sources": [], "rows": []})
    summ = summarize(recs)
    csv_path = tmp_path / "out.csv"
    json_path = tmp_path / "out.json"
    write_csv(recs, csv_path)
    write_json(recs, summ, json_path)
    with csv_path.open(encoding="utf-8") as fh:
        header = next(_csv.reader(fh))
    assert "status" in header and "source_reliability" in header and "next_action" in header
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["needs_research"] == 1
    assert len(payload["records"]) == 1


def test_main_writes_outputs(tmp_path):
    ref = _make_xlsx(tmp_path / "ref.xlsx", [
        ["BNP Paribas", "", "", "Lyon", "Rhône", "", "", "", "", "", "V2", "", "", "", "90", "Confirmé", ""],
    ])
    payload_path = tmp_path / "data.json"
    payload_path.write_text(json.dumps({"closures": []}), encoding="utf-8")
    rc = main([str(ref), "--payload", str(payload_path), "--out-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "copilot_coverage.csv").exists()
    assert (tmp_path / "copilot_coverage.json").exists()
    out = json.loads((tmp_path / "copilot_coverage.json").read_text(encoding="utf-8"))
    # Invariant : aucune ligne sans status/next_action/source_reliability.
    for r in out["records"]:
        assert r["status"] and r["next_action"] and r["source_reliability"]
```

- [ ] **Step 2: Lancer le test pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -k "compare or write_ or main" -v`
Expected: FAIL avec `ImportError`.

- [ ] **Step 3: Écrire l'implémentation**

```python
# tools/compare_copilot_coverage.py (ajouter)
import argparse
import csv
import sys
from datetime import datetime, timezone

DEFAULT_PAYLOAD = "data/export/data.json"
DEFAULT_OVERRIDES = "tools/copilot_overrides.json"
DEFAULT_OUT_DIR = "data/export"


def compare(rows: list[dict], payload: dict, overrides: dict) -> list[dict]:
    return [build_record(row, payload, overrides) for row in rows]


def summarize(records: list[dict]) -> dict:
    summary = {status: 0 for status in COVERAGE_STATUSES}
    reliability = {"high": 0, "medium": 0, "low": 0}
    for r in records:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
        reliability[r["source_reliability"]] = reliability.get(r["source_reliability"], 0) + 1
    matched = sum(1 for r in records if r["matched_pipeline"] == "oui")
    total = len(records)
    return {
        **summary,
        "total": total,
        "matched_pipeline": matched,
        "coverage_pct": round(100 * matched / total, 1) if total else 0.0,
        "reliability": reliability,
        "unexplained": sum(1 for r in records
                           if not (r["status"] and r["next_action"] and r["source_reliability"])),
    }


def write_csv(records: list[dict], path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RECORD_FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, "") for k in RECORD_FIELDS})


def write_json(records: list[dict], summary: dict, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "records": records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark de couverture Copilot (read-only).")
    parser.add_argument("reference", help="Excel de référence Copilot (.xlsx)")
    parser.add_argument("--payload", default=DEFAULT_PAYLOAD, help="Chemin vers data.json")
    parser.add_argument("--overrides", default=DEFAULT_OVERRIDES, help="Chemin vers copilot_overrides.json")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Répertoire de sortie")
    args = parser.parse_args(argv)

    rows = load_copilot_rows(args.reference)
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8")) if Path(args.payload).exists() else {}
    overrides = load_overrides(args.overrides)
    records = compare(rows, payload, overrides)
    summary = summarize(records)

    out_dir = Path(args.out_dir)
    write_csv(records, out_dir / "copilot_coverage.csv")
    write_json(records, summary, out_dir / "copilot_coverage.json")

    print("--- Couverture Copilot ---")
    for status in COVERAGE_STATUSES:
        print(f"{status:<22} {summary[status]}")
    print(f"{'total':<22} {summary['total']}")
    print(f"{'matched (%)':<22} {summary['matched_pipeline']} ({summary['coverage_pct']}%)")
    print(f"{'fiabilité':<22} {summary['reliability']}")
    print(f"{'lignes inexpliquées':<22} {summary['unexplained']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Lancer toute la suite pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_compare_copilot_coverage.py -v`
Expected: PASS (tous les tests).

- [ ] **Step 5: Vérification sur l'Excel réel (manuel, read-only)**

Run :
```bash
python3.12 -m tools.compare_copilot_coverage \
  liste_agences_bancaires_fermetures_a_partir_2026_v4_CE_complement.xlsx \
  --payload data/export/data.json \
  --overrides tools/copilot_overrides.json \
  --out-dir data/export
```
Expected : récap affiché ; `total 76` ; `lignes inexpliquées 0` ; fichiers
`data/export/copilot_coverage.csv` et `.json` créés. Vérifier dans le CSV que les
35 lignes MoneyVox ont `source_reliability=medium`/`source_flag=article_list_secondary`,
les 30 lignes V2 sans URL ont `source_flag=inherited_source_to_trace`, et que la
ligne Reuilly (`Crédit Agricole Centre Ouest`) a `source_flag=confirmed`.

- [ ] **Step 6: Lancer la suite complète du dépôt (non-régression)**

Run: `python3.12 -m pytest -q`
Expected: PASS (aucune régression sur les tests existants).

- [ ] **Step 7: Commit**

```bash
git add tools/compare_copilot_coverage.py tests/test_compare_copilot_coverage.py data/export/copilot_coverage.csv data/export/copilot_coverage.json
git commit -m "feat(copilot): writers CSV/JSON, récap, CLI + rapport de couverture"
```

---

## Self-Review (effectuée)

- **Couverture du spec** : loader Excel (Task 1) ; overrides JSON + dept nom→code (Task 2) ; 6 statuts de couverture (Task 3, + rejected/confirmed via override Task 5) ; axe fiabilité high/medium/low + flags (Task 4) ; next_action requêtes (Task 5) ; CSV+JSON+récap+CLI (Task 6) ; invariant testé (Task 5 & 6) ; vérif Excel réel 76 lignes / 0 inexpliquée (Task 6 step 5). Read-only respecté partout.
- **Placeholders** : aucun — chaque step de code montre le code complet.
- **Cohérence des types** : `classify_coverage` renvoie `{status, match_type, pipeline_id, pipeline_status}` consommé tel quel par `build_record` ; `apply_reliability` renvoie un dict dont les clés `_source_default_*` sont consommées par `build_record` ; `RECORD_FIELDS` aligné entre `build_record`, `write_csv`, et le test de colonnes.
- **Note de scope** : le mapping Excel est positionnel (l'en-tête banque `²` rend l'alias d'en-tête inutile) ; le repli par alias d'en-tête mentionné dans le spec est volontairement non implémenté (YAGNI sur un fichier committé stable).
- **Donnée réelle** : sur `data.json` actuel, `present_unlocated`/`present_department` ne se déclencheront pas (toutes les closures sont géocodées, 0 vigilance avec département). Ces branches sont couvertes par fixtures. C'est l'état honnête du benchmark.
