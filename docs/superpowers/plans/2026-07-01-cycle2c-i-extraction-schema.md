# Cycle 2c-i — Nouveau schéma d'extraction Haiku + mapping — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer l'extraction single-closure par un schéma riche Haiku (`ExtractionResult` : article_type, closures[], department_signals[], vague_signals[], confidence, needs_sonnet), le mapper vers le stockage actuel (closures + une vigilance agrégée par article), et persister le JSON riche dans le cache d'extraction pour le Cycle 3.

**Architecture:** Nouveaux modèles Pydantic + `extract_structured()` dans `extractor.py` (Haiku, fallback Sonnet/OpenAI sur erreur API) ; module pur `ingest_map.map_result()` traduit le résultat vers des closures internes + une vigilance agrégée ; `run_pipeline` boucle sur les closures[] (rétention temporelle + validation par closure) et route la vigilance ; `openai_fallback` gagne une variante structurée sans toucher le legacy ; bump `EXTRACTION_VERSION` 1→2.

**Tech Stack:** Python 3.12, Pydantic v2, anthropic SDK (`client.messages.parse`), pytest.

## Global Constraints

- **Interpréteur : `python3.12`** uniquement.
- **Listes Pydantic** : `Field(default_factory=list)` (jamais `= []`).
- **`confidence`** présent au niveau `ExtractionResult` ET `VagueSignal` (nécessaire à 2c-ii).
- **`extract_openai()` legacy conservé** ; ajout séparé `extract_openai_structured` + `_schema_structured`.
- **Ancien `Extraction`/`extract()` conservés** (utilisés par `vigilance_review`, non migré).
- **JSON riche persisté** : `extract_structured(...).model_dump()` → `extract_cached` stocke `result_json` (aucune modif du cache 2a).
- **`EXTRACTION_VERSION` 1→2** (invalide le cache 2a proprement).
- **Une seule vigilance par article** (contrainte `vigilances.UNIQUE(url)`) ; détail par signal dans `extractions.result_json`.
- **Mapping** : closure_type merge/regroupement→`fusion`, autres→`fermeture` ; status confirmed→`confirmé`, announced→`projet`, autres→`rumeur` ; `fiabilite=round(confidence*5)` borné 0-5 ; `statut_temporel` dérivé (date future→a_venir, passée→deja_fermee ; sinon announced/threatened→a_venir, sinon inconnu) ; `is_physical_agency=false` ou banque inconnue ou commune vide → closure ignoré.
- **run.py** : le pipeline principal branche `extract_structured(...).model_dump()` ; `vigilance_review` garde `extract`.

---

## Structure des fichiers

- **Modify** `backend/extractor.py` : modèles `ClosureItem/DeptSignal/VagueSignal/ExtractionResult` + `_INSTRUCTIONS_STRUCTURED` + `build_messages_structured` + `extract_structured` ; généraliser `_parse_avec_retries` (param `output_format`, `max_tokens`).
- **Create** `backend/ingest_map.py` : `map_result`.
- **Modify** `backend/openai_fallback.py` : `_schema_structured` + `extract_openai_structured` (legacy intact).
- **Modify** `config.py` : `EXTRACTION_VERSION = 2`.
- **Modify** `backend/pipeline.py` : consommation structurée + helper `_ingest_closure`.
- **Modify** `run.py` : extractor_fn structuré.
- **Tests** : `tests/test_extractor.py`, `tests/test_ingest_map.py` (create), `tests/test_openai_fallback.py`, `tests/test_pipeline.py`.

---

### Task 1: Modèles Pydantic + `extract_structured` (extractor.py)

**Files:**
- Modify: `backend/extractor.py`
- Test: `tests/test_extractor.py`

**Interfaces:**
- Produces: `ClosureItem`, `DeptSignal`, `VagueSignal`, `ExtractionResult` (Pydantic) ; `build_messages_structured(article, aujourdhui=None) -> list[dict]` ; `extract_structured(article, client, model=config.ANTHROPIC_MODEL, aujourdhui=None) -> ExtractionResult`.
- `_parse_avec_retries` gagne `output_format=Extraction` et `max_tokens=1024` (défauts → legacy inchangé).

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_extractor.py (ajouter)
import config
from backend.extractor import (
    ExtractionResult, ClosureItem, DeptSignal, VagueSignal, extract_structured,
)


class _FakeResp:
    def __init__(self, parsed): self.parsed_output = parsed


class _FakeMessages:
    def __init__(self, results): self._results = list(results); self.calls = []

    def parse(self, **kw):
        self.calls.append(kw)
        r = self._results.pop(0)
        if isinstance(r, Exception):
            raise r
        return _FakeResp(r)


class _FakeClient:
    def __init__(self, results): self.messages = _FakeMessages(results)


class _ApiErr(Exception):
    def __init__(self, code): super().__init__(f"api {code}"); self.status_code = code


def _item(**kw):
    base = dict(bank="BNP", commune="Lyon", status="announced",
                closure_type="closure", confidence=0.7, evidence="…")
    base.update(kw)
    return ClosureItem(**base)


def _art():
    return {"titre": "BNP ferme", "texte": "agence de Lyon", "departement": "69"}


def test_extract_structured_single_closure():
    res = ExtractionResult(article_type="single_closure", closures=[_item()])
    client = _FakeClient([res])
    out = extract_structured(_art(), client=client)
    assert out.article_type == "single_closure"
    assert len(out.closures) == 1 and out.closures[0].commune == "Lyon"


def test_extract_structured_list_closures():
    res = ExtractionResult(article_type="list_closures",
                           closures=[_item(commune="Bessines"), _item(commune="Tulle"),
                                     _item(commune="Guéret")])
    out = extract_structured(_art(), client=_FakeClient([res]))
    assert len(out.closures) == 3


def test_extract_structured_out_of_scope_non_none():
    res = ExtractionResult(article_type="out_of_scope")
    out = extract_structured(_art(), client=_FakeClient([res]))
    assert out is not None and out.closures == [] and out.department_signals == []


def test_extract_structured_fallback_sonnet_sur_erreur(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "0")
    res = ExtractionResult(article_type="single_closure", closures=[_item()])
    client = _FakeClient([_ApiErr(529), res])  # 1er appel échoue, fallback réussit
    out = extract_structured(_art(), client=client)
    assert len(out.closures) == 1
    assert client.messages.calls[0]["model"] == config.ANTHROPIC_MODEL
    assert client.messages.calls[1]["model"] == config.ANTHROPIC_FALLBACK_MODEL
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_extractor.py -k structured -v`
Expected: FAIL (`ImportError: cannot import name 'ExtractionResult'`).

- [ ] **Step 3: Implémenter dans `backend/extractor.py`**

Ajouter les modèles après la classe `Extraction` existante :

```python
class ClosureItem(BaseModel):
    bank: str
    agency_label: str = ""
    commune: str
    departement: Optional[str] = None
    region: Optional[str] = None
    address: str = ""
    closure_date: Optional[str] = None
    date_precision: Literal["exact", "month", "year", "approximate", "unknown"] = "unknown"
    status: Literal["confirmed", "announced", "contested", "threatened", "unclear"]
    closure_type: Literal["closure", "regroupement", "transfer", "merge", "threatened_closure"]
    is_physical_agency: bool = True
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = ""


class DeptSignal(BaseModel):
    bank: str
    departement: Optional[str] = None
    count: Optional[int] = None
    communes_mentioned: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence: str = ""


class VagueSignal(BaseModel):
    bank: str = ""
    scope: Literal["regional", "national", "unknown"] = "unknown"
    count: Optional[int] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence: str = ""


class ExtractionResult(BaseModel):
    article_type: Literal["single_closure", "list_closures", "department_signal",
                          "regional_signal", "national_signal", "social_hr",
                          "out_of_scope", "ambiguous"]
    source_reliability: Literal["primary", "local_press", "national_press",
                                "aggregator", "weak"] = "weak"
    closures: list[ClosureItem] = Field(default_factory=list)
    department_signals: list[DeptSignal] = Field(default_factory=list)
    vague_signals: list[VagueSignal] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_sonnet: bool = False
    reason: str = ""


_INSTRUCTIONS_STRUCTURED = (
    "Tu analyses un article de presse français sur d'éventuelles fermetures, "
    "regroupements ou transferts d'agences BANCAIRES physiques en France. "
    "Classe l'article dans article_type. Pour chaque agence NOMMÉE (commune précise), "
    "ajoute un élément à closures[] ; si l'article cite plusieurs agences (article-liste), "
    "renvoie-les TOUTES. N'invente jamais de commune. "
    "Un signal départemental chiffré sans communes précises (ex. '10 agences dans le Cher') "
    "va dans department_signals[]. Un signal régional/national vague va dans vague_signals[]. "
    "is_physical_agency=false pour distributeur (DAB), service en ligne ou hors agence. "
    "closure_type: closure|regroupement|transfer|merge|threatened_closure. "
    "status: confirmed|announced|contested|threatened|unclear. "
    "date_precision et closure_date (ISO) si connues. "
    "confidence (0..1) par closure ET global. needs_sonnet=true si ambigu/complexe. "
    "evidence: courte citation textuelle justifiant."
)


def build_messages_structured(article: dict, aujourdhui: Optional[str] = None) -> list[dict]:
    aujourdhui = aujourdhui or date.today().isoformat()
    corps = (
        f"{_INSTRUCTIONS_STRUCTURED}\n\n"
        f"DATE DU JOUR: {aujourdhui}\n"
        f"TITRE: {article.get('titre','')}\n"
        f"TEXTE: {article.get('texte','')}\n"
        f"DÉPARTEMENT (indice): {article.get('departement')}"
    )
    return [{"role": "user", "content": corps}]
```

Généraliser `_parse_avec_retries` (remplacer sa signature et l'appel `parse`) :

```python
def _parse_avec_retries(client, *, model: str, messages: list[dict], sleep_fn=time.sleep,
                        output_format=Extraction, max_tokens: int = 1024):
    max_retries = max(0, _int_env("ANTHROPIC_MAX_RETRIES", _DEFAULT_MAX_RETRIES))
    base = max(0.0, _float_env("ANTHROPIC_RETRY_BASE_SECONDS", _DEFAULT_RETRY_BASE_SECONDS))
    plafond = max(base, _float_env("ANTHROPIC_RETRY_MAX_SECONDS", _DEFAULT_RETRY_MAX_SECONDS))
    for tentative in range(max_retries + 1):
        try:
            return client.messages.parse(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                output_format=output_format,
            )
        except Exception as exc:
            status = _status_code(exc)
            if status not in _RETRY_STATUS_CODES or tentative >= max_retries:
                raise
            attente = min(plafond, base * (2 ** tentative))
            print(f"[extractor] Anthropic {status} — nouvelle tentative dans {attente:g}s")
            sleep_fn(attente)
```

Ajouter `extract_structured` :

```python
def extract_structured(article: dict, client, model: str = config.ANTHROPIC_MODEL,
                       aujourdhui: Optional[str] = None) -> "ExtractionResult":
    aujourdhui = aujourdhui or date.today().isoformat()
    messages = build_messages_structured(article, aujourdhui)
    fallback_model = _fallback_model(model)
    try:
        response = _parse_avec_retries(
            client, model=model, messages=messages,
            output_format=ExtractionResult, max_tokens=2048,
        )
        return response.parsed_output
    except Exception as exc:
        if _status_code(exc) in _RETRY_STATUS_CODES and fallback_model:
            response = _parse_avec_retries(
                client, model=fallback_model, messages=messages,
                output_format=ExtractionResult, max_tokens=2048,
            )
            return response.parsed_output
        if (_status_code(exc) in _RETRY_STATUS_CODES
                and os.environ.get("OPENAI_API_KEY")
                and os.environ.get("OPENAI_FALLBACK_ENABLED", "1") != "0"):
            from backend.openai_fallback import extract_openai_structured
            return extract_openai_structured(article, aujourdhui)
        raise
```

(Le fallback profond OpenAI référence `extract_openai_structured`, implémenté en Task 3 ; non exercé par les tests de cette task.)

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_extractor.py -v`
Expected: PASS (existants + nouveaux `structured`).

- [ ] **Step 5: Commit**

```bash
git add backend/extractor.py tests/test_extractor.py
git commit -m "feat(2c-i): modèles ExtractionResult + extract_structured (Haiku, fallback erreur)"
```

---

### Task 2: `backend/ingest_map.py` — `map_result`

**Files:**
- Create: `backend/ingest_map.py`
- Test: `tests/test_ingest_map.py`

**Interfaces:**
- Consumes: `backend.dedup.closure_id`, `backend.extractor.normalise_banque`, `backend.extractor.banque_connue`.
- Produces: `map_result(result: dict, article: dict, aujourdhui: str) -> tuple[list[dict], dict | None]`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_ingest_map.py
from backend.ingest_map import map_result

_TODAY = "2026-07-01"


def _art():
    return {"titre": "T", "texte": "x", "url": "http://a", "source": "GN",
            "date": "2026-01-10", "departement": "69"}


def _res(**kw):
    base = {"article_type": "single_closure", "closures": [],
            "department_signals": [], "vague_signals": []}
    base.update(kw)
    return base


def _clo(**kw):
    base = dict(bank="BNP", commune="Lyon", status="announced", closure_type="closure",
                confidence=0.8, is_physical_agency=True, date_precision="unknown",
                closure_date=None, evidence="preuve", agency_label="Lyon centre",
                address="1 rue X", departement="69")
    base.update(kw)
    return base


def test_map_closure_fields():
    closures, vig = map_result(_res(closures=[_clo()]), _art(), _TODAY)
    assert vig is None
    assert len(closures) == 1
    c = closures[0]
    assert c["banque"] == "BNP Paribas"          # normalise_banque
    assert c["type"] == "fermeture"              # closure_type=closure
    assert c["statut"] == "projet"               # status=announced
    assert c["fiabilite"] == 4                    # round(0.8*5)
    assert c["agence_localisation"] == "Lyon centre"
    assert c["adresse"] == "1 rue X"
    assert c["citation"] == "preuve"


def test_map_closure_type_et_statut():
    closures, _ = map_result(_res(closures=[_clo(closure_type="merge", status="confirmed")]), _art(), _TODAY)
    assert closures[0]["type"] == "fusion"
    assert closures[0]["statut"] == "confirmé"


def test_statut_temporel_derive():
    fut, _ = map_result(_res(closures=[_clo(closure_date="2027-01-01")]), _art(), _TODAY)
    assert fut[0]["statut_temporel"] == "a_venir"
    pas, _ = map_result(_res(closures=[_clo(closure_date="2020-01-01")]), _art(), _TODAY)
    assert pas[0]["statut_temporel"] == "deja_fermee"
    ann, _ = map_result(_res(closures=[_clo(closure_date=None, status="announced")]), _art(), _TODAY)
    assert ann[0]["statut_temporel"] == "a_venir"
    conf, _ = map_result(_res(closures=[_clo(closure_date=None, status="confirmed")]), _art(), _TODAY)
    assert conf[0]["statut_temporel"] == "inconnu"


def test_ignore_non_physique_et_banque_inconnue():
    c1 = _clo(is_physical_agency=False)
    c2 = _clo(bank="Boulangerie Dupont")
    closures, _ = map_result(_res(closures=[c1, c2]), _art(), _TODAY)
    assert closures == []


def test_department_signal_vers_vigilance_agregee():
    res = _res(article_type="department_signal",
               department_signals=[{"bank": "BNP", "departement": "18", "count": 10,
                                    "communes_mentioned": ["Bourges"], "confidence": 0.6,
                                    "evidence": "10 agences dans le Cher"}])
    closures, vig = map_result(res, _art(), _TODAY)
    assert closures == []
    assert vig is not None
    assert vig["departement"] == "18"
    assert vig["score"] == 3                       # round(0.6*5)
    assert vig["url"] == "http://a"
    assert "dept" in vig["raison"]


def test_vague_signal_vers_vigilance_sans_departement():
    res = _res(article_type="national_signal",
               vague_signals=[{"bank": "", "scope": "national", "count": None,
                               "confidence": 0.2, "evidence": "vague"}])
    closures, vig = map_result(res, _art(), _TODAY)
    assert closures == []
    assert vig is not None and vig["departement"] is None
    assert "vague" in vig["raison"]
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_ingest_map.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.ingest_map`).

- [ ] **Step 3: Implémenter `backend/ingest_map.py`**

```python
"""Mapping du schéma d'extraction riche (Cycle 2c-i) vers le stockage actuel.

map_result() traduit un ExtractionResult (dict) en :
  - une liste de closures internes (pour la table closures) ;
  - AU PLUS une vigilance agrégée par article (contrainte vigilances.UNIQUE(url)) ;
    le détail par signal reste dans extractions.result_json (Cycle 3).
Calcul pur, best-effort : aucune exception, aucune écriture DB.
"""
from __future__ import annotations

import hashlib
from datetime import date

from backend.dedup import closure_id
from backend.extractor import banque_connue, normalise_banque

_TYPE_MAP = {"closure": "fermeture", "transfer": "fermeture",
             "threatened_closure": "fermeture", "regroupement": "fusion", "merge": "fusion"}
_STATUT_MAP = {"confirmed": "confirmé", "announced": "projet",
               "contested": "rumeur", "threatened": "rumeur", "unclear": "rumeur"}


def _fiab(confidence) -> int:
    try:
        return max(0, min(5, round(float(confidence) * 5)))
    except (TypeError, ValueError):
        return 0


def _statut_temporel(closure_date, status, aujourdhui) -> str:
    if closure_date:
        try:
            d = date.fromisoformat(str(closure_date)[:10])
            today = date.fromisoformat(str(aujourdhui)[:10])
            return "a_venir" if d >= today else "deja_fermee"
        except ValueError:
            pass
    return "a_venir" if status in ("announced", "threatened") else "inconnu"


def _map_closure(c: dict, article: dict, aujourdhui: str) -> dict | None:
    if not c.get("is_physical_agency", True):
        return None
    commune = (c.get("commune") or "").strip()
    if not commune:
        return None
    banque = normalise_banque(c.get("bank") or "")
    if not banque_connue(banque):
        return None
    type_ = _TYPE_MAP.get(c.get("closure_type"), "fermeture")
    return {
        "id": closure_id(banque, commune, type_),
        "banque": banque, "commune": commune, "code_insee": None,
        "departement": c.get("departement") or article.get("departement"),
        "type": type_,
        "date_annonce": article.get("date") or None,
        "date_fermeture": c.get("closure_date"),
        "statut": _STATUT_MAP.get(c.get("status"), "rumeur"),
        "statut_temporel": _statut_temporel(c.get("closure_date"), c.get("status"), aujourdhui),
        "date_fermeture_approx": 0 if c.get("date_precision") == "exact" else 1,
        "fiabilite": _fiab(c.get("confidence")),
        "lat": None, "lon": None,
        "citation": c.get("evidence") or "",
        "adresse": c.get("address") or None,
        "agence_localisation": c.get("agency_label") or None,
    }


def _aggregate_vigilance(dept: list, vague: list, article: dict) -> dict:
    url = article.get("url") or ""
    parts, evidences, confidences = [], [], []
    banque, departement = None, None
    for s in dept:
        b = normalise_banque(s.get("bank") or "") if s.get("bank") else None
        banque = banque or b
        departement = departement or s.get("departement")
        parts.append(f"dept({b},{s.get('departement')},count={s.get('count')})")
        if s.get("evidence"):
            evidences.append(s["evidence"])
        confidences.append(float(s.get("confidence") or 0))
    for s in vague:
        b = normalise_banque(s.get("bank") or "") if s.get("bank") else None
        banque = banque or b
        parts.append(f"vague({b},{s.get('scope')},count={s.get('count')})")
        if s.get("evidence"):
            evidences.append(s["evidence"])
        confidences.append(float(s.get("confidence") or 0))
    key = url or (article.get("titre") or "")
    return {
        "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
        "banque": banque, "departement": departement,
        "titre": article.get("titre"), "extrait": " | ".join(evidences)[:500],
        "url": url, "source": article.get("source"), "date": article.get("date"),
        "score": round(max(confidences) * 5) if confidences else 0,
        "raison": "signaux: " + "; ".join(parts),
    }


def map_result(result: dict, article: dict, aujourdhui: str) -> tuple[list[dict], dict | None]:
    closures = []
    for c in result.get("closures") or []:
        mapped = _map_closure(c, article, aujourdhui)
        if mapped is not None:
            closures.append(mapped)
    dept = result.get("department_signals") or []
    vague = result.get("vague_signals") or []
    vig = _aggregate_vigilance(dept, vague, article) if (dept or vague) else None
    return closures, vig
```

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_ingest_map.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/ingest_map.py tests/test_ingest_map.py
git commit -m "feat(2c-i): ingest_map.map_result — schéma riche -> closures + vigilance agrégée"
```

---

### Task 3: `openai_fallback` variante structurée

**Files:**
- Modify: `backend/openai_fallback.py`
- Test: `tests/test_openai_fallback.py`

**Interfaces:**
- Consumes: `backend.extractor.ExtractionResult`, `backend.extractor.build_messages_structured`.
- Produces: `_schema_structured() -> dict` ; `extract_openai_structured(article, aujourdhui, fetch=None, budget_path=None) -> ExtractionResult`.
- Le legacy `extract_openai` / `_schema` reste inchangé.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_openai_fallback.py (ajouter)
import json as _json

from backend.extractor import ExtractionResult
from backend import openai_fallback


def _structured_content():
    return _json.dumps({
        "article_type": "single_closure", "source_reliability": "local_press",
        "closures": [{
            "bank": "BNP", "agency_label": "", "commune": "Lyon", "departement": "69",
            "region": None, "address": "", "closure_date": "2026-06-30",
            "date_precision": "exact", "status": "announced", "closure_type": "closure",
            "is_physical_agency": True, "confidence": 0.8, "evidence": "…"}],
        "department_signals": [], "vague_signals": [], "confidence": 0.8,
        "needs_sonnet": False, "reason": "",
    })


def test_extract_openai_structured_parse(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def fake_post(url, api_key, payload):
        return {"choices": [{"message": {"content": _structured_content()}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20}}

    out = openai_fallback.extract_openai_structured(
        {"titre": "BNP ferme", "texte": "Lyon", "departement": "69"},
        "2026-07-01", fetch=fake_post, budget_path=tmp_path / "b.json")
    assert isinstance(out, ExtractionResult)
    assert out.article_type == "single_closure"
    assert out.closures[0].commune == "Lyon"


def test_schema_structured_a_les_cles():
    sch = openai_fallback._schema_structured()
    assert sch["type"] == "object"
    assert "closures" in sch["properties"]
    assert "department_signals" in sch["properties"]
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_openai_fallback.py -k structured -v`
Expected: FAIL (`AttributeError: extract_openai_structured`).

- [ ] **Step 3: Implémenter dans `backend/openai_fallback.py`**

Ajouter l'import en tête : `from backend.extractor import ExtractionResult, build_messages_structured`.

```python
def _schema_structured() -> dict:
    closure = {
        "type": "object", "additionalProperties": False,
        "required": ["bank", "agency_label", "commune", "departement", "region",
                     "address", "closure_date", "date_precision", "status",
                     "closure_type", "is_physical_agency", "confidence", "evidence"],
        "properties": {
            "bank": {"type": "string"}, "agency_label": {"type": "string"},
            "commune": {"type": "string"}, "departement": {"type": ["string", "null"]},
            "region": {"type": ["string", "null"]}, "address": {"type": "string"},
            "closure_date": {"type": ["string", "null"]},
            "date_precision": {"type": "string",
                               "enum": ["exact", "month", "year", "approximate", "unknown"]},
            "status": {"type": "string",
                       "enum": ["confirmed", "announced", "contested", "threatened", "unclear"]},
            "closure_type": {"type": "string",
                             "enum": ["closure", "regroupement", "transfer", "merge", "threatened_closure"]},
            "is_physical_agency": {"type": "boolean"},
            "confidence": {"type": "number"}, "evidence": {"type": "string"},
        },
    }
    dept = {
        "type": "object", "additionalProperties": False,
        "required": ["bank", "departement", "count", "communes_mentioned", "confidence", "evidence"],
        "properties": {
            "bank": {"type": "string"}, "departement": {"type": ["string", "null"]},
            "count": {"type": ["integer", "null"]},
            "communes_mentioned": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"}, "evidence": {"type": "string"},
        },
    }
    vague = {
        "type": "object", "additionalProperties": False,
        "required": ["bank", "scope", "count", "confidence", "evidence"],
        "properties": {
            "bank": {"type": "string"},
            "scope": {"type": "string", "enum": ["regional", "national", "unknown"]},
            "count": {"type": ["integer", "null"]},
            "confidence": {"type": "number"}, "evidence": {"type": "string"},
        },
    }
    return {
        "type": "object", "additionalProperties": False,
        "required": ["article_type", "source_reliability", "closures",
                     "department_signals", "vague_signals", "confidence", "needs_sonnet", "reason"],
        "properties": {
            "article_type": {"type": "string",
                             "enum": ["single_closure", "list_closures", "department_signal",
                                      "regional_signal", "national_signal", "social_hr",
                                      "out_of_scope", "ambiguous"]},
            "source_reliability": {"type": "string",
                                   "enum": ["primary", "local_press", "national_press",
                                            "aggregator", "weak"]},
            "closures": {"type": "array", "items": closure},
            "department_signals": {"type": "array", "items": dept},
            "vague_signals": {"type": "array", "items": vague},
            "confidence": {"type": "number"},
            "needs_sonnet": {"type": "boolean"}, "reason": {"type": "string"},
        },
    }


def extract_openai_structured(article: dict, aujourdhui: str, fetch=None,
                              budget_path=None) -> ExtractionResult:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY absente")
    fetch = fetch or _post
    model = os.environ.get("OPENAI_FALLBACK_MODEL", DEFAULT_MODEL)
    max_output = int(_float_env("OPENAI_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS))
    messages = build_messages_structured(article, aujourdhui)
    input_estimate = _token_estimate(messages)
    _assert_budget(input_estimate, max_output, budget_path)
    payload = {
        "model": model, "messages": messages, "max_completion_tokens": max_output,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "extraction_structuree", "strict": True, "schema": _schema_structured()}},
    }
    response = fetch(OPENAI_CHAT_URL, api_key, payload)
    usage = response.get("usage") or {}
    input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or input_estimate
    output_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or max_output
    _record_usage(int(input_tokens), int(output_tokens), budget_path)
    content = response["choices"][0]["message"]["content"]
    return ExtractionResult.model_validate_json(content)
```

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_openai_fallback.py -v`
Expected: PASS (legacy + structured).

- [ ] **Step 5: Commit**

```bash
git add backend/openai_fallback.py tests/test_openai_fallback.py
git commit -m "feat(2c-i): extract_openai_structured + _schema_structured (legacy intact)"
```

---

### Task 4: Intégration pipeline + run.py + bump version

**Files:**
- Modify: `config.py`, `backend/pipeline.py`, `run.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `ingest_map.map_result`, `extractor.extract_structured`, `extractor._retenir_fermeture`.
- `EXTRACTION_VERSION = 2`.

- [ ] **Step 1: Migrer/écrire les tests**

Dans `tests/test_pipeline.py`, remplacer le helper `_extractor` par une forme structurée et ajouter les nouveaux tests :

```python
# REMPLACER _extractor par :
def _extractor(article):
    return {
        "article_type": "single_closure",
        "closures": [{
            "bank": "BNP", "agency_label": "", "commune": "Lyon", "departement": "69",
            "region": None, "address": "", "closure_date": None, "date_precision": "unknown",
            "status": "announced", "closure_type": "closure", "is_physical_agency": True,
            "confidence": 0.6, "evidence": "agence fermée à Lyon",
        }],
        "department_signals": [], "vague_signals": [], "confidence": 0.6,
        "needs_sonnet": False, "reason": "",
    }


def _structured(**closure_over):
    r = _extractor({})
    r["closures"][0].update(closure_over)
    return r
```

Adapter les assertions dépendant de l'ancien id / forme :

```python
# test_pipeline_complet : remplacer la ligne d'assertion id='abc123' par :
    row = conn.execute("SELECT lat, lon FROM closures WHERE commune='Lyon'").fetchone()
    assert row == (45.76, 4.85)

# test_pipeline_enrichit_departement_si_absent : remplacer extractor_sans_dept par :
    def extractor_sans_dept(article):
        r = _extractor(article); r["closures"][0]["departement"] = None; return r
    ...
    row = conn.execute("SELECT departement, code_insee FROM closures WHERE commune='Lyon'").fetchone()
    assert row == ("69", "69123")

# test_pipeline_idempotent : inchangé sauf compter par commune
    n = conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0]
    assert n == 1

# test_pipeline_rejette_commune_inconnue_ou_non_nominative : remplacer extractor par :
    def extractor(_article):
        return _structured(commune="inconnu", departement=None)
    ...
    assert "commune" in vus[0][1]

# test_pipeline_rejette_territoire_pris_pour_commune : remplacer extractor par :
    def extractor(_article):
        return _structured(commune="Franche-Comté", departement=None)
```

Ajouter les nouveaux tests :

```python
def test_pipeline_list_closures_explose_en_n_fermetures(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    def extractor(_a):
        base = _extractor(_a)["closures"][0]
        def item(commune):
            c = dict(base); c["commune"] = commune; return c
        return {"article_type": "list_closures",
                "closures": [item("Bessines"), item("Tulle"), item("Guéret")],
                "department_signals": [], "vague_signals": [], "confidence": 0.6,
                "needs_sonnet": False, "reason": ""}
    geo = lambda commune, dept: {"lat": 45.0, "lon": 2.0, "code_insee": "00000", "departement": "19"}
    recap = pipeline.run_pipeline(conn, [lambda: [_article("http://list")]],
                                  extractor, geo, enrich_fn=lambda u: "")
    assert recap["fermetures"] == 3
    assert conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0] == 3


def test_pipeline_department_signal_route_vigilance(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    def extractor(_a):
        return {"article_type": "department_signal", "closures": [],
                "department_signals": [{"bank": "BNP", "departement": "18", "count": 10,
                                        "communes_mentioned": ["Bourges"], "confidence": 0.6,
                                        "evidence": "10 agences dans le Cher"}],
                "vague_signals": [], "confidence": 0.6, "needs_sonnet": False, "reason": ""}
    recap = pipeline.run_pipeline(conn, [lambda: [_article("http://dep")]],
                                  extractor, _geo, enrich_fn=lambda u: "")
    assert recap["fermetures"] == 0
    assert conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM vigilances").fetchone()[0] == 1


def test_pipeline_persiste_json_riche(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    pipeline.run_pipeline(conn, [lambda: [_article("http://rich")]], _extractor, _geo,
                          enrich_fn=lambda u: "")
    row = conn.execute("SELECT result_json FROM extractions").fetchone()
    assert row is not None and "article_type" in row[0]
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_pipeline.py -k "list_closures or department_signal or persiste" -v`
Expected: FAIL (pipeline consomme encore la forme single-closure ; `map_result` non câblé).

- [ ] **Step 3: Implémenter — config, pipeline, run.py**

`config.py` : `EXTRACTION_VERSION = int(os.getenv("EXTRACTION_VERSION", "2"))` (défaut 1 → 2).

`backend/pipeline.py` : ajouter aux imports `extractor, ingest_map` :

```python
from backend import commune_normalize, context_builder, extractor, ingest_map, prefilter, store, validation
```

Ajouter le helper (au niveau module, après `ingest_closures`) :

```python
def _ingest_closure(conn, resultat, art, url, geocoder_fn, recap):
    geo = geocoder_fn(resultat["commune"], resultat.get("departement"))
    if geo:
        resultat["lat"] = geo.get("lat")
        resultat["lon"] = geo.get("lon")
        if not validation.departement_valide(resultat.get("departement")):
            resultat["departement"] = geo.get("departement")
        if not resultat.get("code_insee"):
            resultat["code_insee"] = geo.get("code_insee")
        resultat = commune_normalize.appliquer(resultat, geo)
    publiable, raison = validation.fermeture_publiable(resultat, geo)
    if not publiable:
        recap["rejets_validation"] += 1
        return False, raison
    store.upsert_closure(conn, resultat)
    store.add_source(conn, resultat["id"], {
        "url": url, "titre": art.get("titre"),
        "source": art.get("source"), "date": art.get("date")})
    recap["fermetures"] += 1
    return True, None
```

Remplacer le bloc de consommation single-closure (de `recap["extraits"] += 1` jusqu'à `recap["fermetures"] += 1` inclus) par la consommation structurée :

```python
            aujourdhui = date.today().isoformat()
            closures_map, sig_vig = ingest_map.map_result(resultat, art, aujourdhui)
            n_pub = 0
            rejets = []
            for c in closures_map:
                if not extractor._retenir_fermeture(
                        c["statut_temporel"], c.get("date_fermeture"), since_date, aujourdhui):
                    rejets.append("hors fenêtre temporelle")
                    continue
                recap["extraits"] += 1
                ok, raison = _ingest_closure(conn, c, art, url, geocoder_fn, recap)
                if ok:
                    n_pub += 1
                elif raison:
                    rejets.append(raison)
            if sig_vig:
                store.upsert_vigilance(conn, sig_vig)
                recap["vigilances"] += 1
            elif n_pub == 0:
                raison = ("fermeture non publiée: " + "; ".join(r for r in rejets if r)
                          if rejets else "article pertinent sans fermeture publiable")
                if vigilance_fn and vigilance_fn(art, raison):
                    recap["vigilances"] += 1
```

`run.py` : remplacer la ligne extractor_fn du pipeline principal :

```python
        extractor_fn=lambda art: extract_structured(art, client=client).model_dump(),
```

et ajouter l'import `from backend.extractor import extract, extract_structured` (garder `extract` pour `vigilance_review`).

- [ ] **Step 4: Lancer (fichier puis suite complète)**

Run: `python3.12 -m pytest tests/test_pipeline.py -v`
Expected: PASS (migrés + nouveaux).

Run: `python3.12 -m pytest -q`
Expected: PASS (aucune régression ; `vigilance_review` utilise toujours le legacy `extract`).

- [ ] **Step 5: Commit**

```bash
git add config.py backend/pipeline.py run.py tests/test_pipeline.py
git commit -m "feat(2c-i): pipeline consomme ExtractionResult (closures[]+vigilance), run.py structuré, EXTRACTION_VERSION=2"
```

---

## Self-Review (effectuée)

- **Couverture du spec** : modèles + `extract_structured` (T1) ; mapping + vigilance agrégée (T2) ; openai structuré séparé, legacy intact (T3) ; pipeline boucle closures[] + rétention/validation par closure + routage vigilance + run.py + `EXTRACTION_VERSION=2` + JSON riche persisté testé (T4). Article-liste = `list_closures` multi (T4 test). `confidence` sur ExtractionResult/VagueSignal (T1). `Field(default_factory=list)` (T1).
- **Placeholders** : aucun ; code complet à chaque step.
- **Cohérence des types** : `extract_structured -> ExtractionResult` ; `run.py .model_dump()` → dict → `extract_cached` → `map_result(dict,…) -> (closures, vigilance|None)` → pipeline. `_ingest_closure` renvoie `(bool, raison)`.
- **Contrainte UNIQUE(url)** : une seule vigilance par article (sig_vig agrégée, sinon fallback unique) — pas de collision.
- **Migration assumée** : le contrat pipeline passe à la forme structurée ; les tests injectant un extracteur single-closure sont migrés (T4). Les tests renvoyant `None` restent valides (branche `resultat is None` conservée en amont de `map_result`). `vigilance_review` garde le legacy `extract()`.
