# Cycle 2b — Préfiltre scoring + détection d'entités + contexte compact — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le préfiltre booléen par un scoring local sans IA (score + entités + phrases pertinentes) et envoyer à l'IA un contexte compact au lieu du texte brut tronqué, en routant les articles clairement faibles en vigilance plutôt que de payer l'IA.

**Architecture:** `prefilter.analyse()` produit un `PrefilterResult` (score + banques/communes/départements/dates/adresses + phrases pertinentes) en réutilisant les helpers heuristiques existants. `context_builder.build_compact_context()` sélectionne les paragraphes pertinents et plafonne la taille. `run_pipeline` gate par score (skip → vigilance) et alimente l'IA avec le contexte compact.

**Tech Stack:** Python 3.12, stdlib (re, unicodedata, dataclasses), pytest. Réutilise `backend.drilldown`, `backend.extractor.normalise_banque`, `config`.

## Global Constraints

- **Interpréteur : `python3.12`** uniquement.
- **Aucune IA, aucun réseau** dans `prefilter`/`context_builder` (calcul pur, best-effort).
- **Détection communes** : heuristique noms propres (pas de dataset). INSEE reste post-IA via `geocode`.
- **Compat** : `is_relevant(article) -> bool` **conservé** à l'identique (banque ET terme).
- **Gate conservateur** : ne sauter l'IA que si `score <= config.PREFILTER_MIN_SCORE` (défaut `-2`) ; l'article sauté part en **vigilance** (jamais perdu).
- **Contexte compact** plafonné à `config.PREFILTER_CONTEXT_MAX_CHARS` (défaut `8000`).
- Constantes : `PREFILTER_MIN_SCORE=-2`, `PREFILTER_CONTEXT_MAX_CHARS=8000`, `RH_TERMS=[...]`.

---

## Structure des fichiers

- **Modify** `backend/prefilter.py` : `PrefilterResult` (dataclass) + `analyse()` + helpers de détection + `is_relevant` conservé. Ajoute `RH_TERMS` dans `config.py`.
- **Create** `backend/context_builder.py` : `build_compact_context()`. Ajoute `PREFILTER_CONTEXT_MAX_CHARS` dans `config.py`.
- **Modify** `backend/pipeline.py` : gate par score + contexte compact. Ajoute `PREFILTER_MIN_SCORE` dans `config.py`.
- **Tests** : `tests/test_prefilter.py` (étendre), **Create** `tests/test_context_builder.py`, `tests/test_pipeline.py` (étendre).

---

### Task 1: `prefilter.analyse()` — scoring + détection d'entités

**Files:**
- Modify: `config.py` (ajout `RH_TERMS`)
- Modify: `backend/prefilter.py`
- Test: `tests/test_prefilter.py`

**Interfaces:**
- Consumes: `config.ENSEIGNES`, `config.MARQUES_REGIONALES`, `config.TERMES_FERMETURE`, `config.DEPARTEMENTS`, `config.RH_TERMS` ; `drilldown.communes_candidates` ; `extractor.normalise_banque`.
- Produces:
  - `@dataclass PrefilterResult(score:int, banks:list[str], communes:list[str], departements:list[str], dates:list[str], addresses:list[str], relevant_sentences:list[str], compact_context:str="")`.
  - `analyse(article: dict) -> PrefilterResult` (remplit tout sauf `compact_context`).
  - `is_relevant(article: dict) -> bool` (inchangé).

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_prefilter.py (ajouter en bas, garder les tests is_relevant existants)
from backend.prefilter import analyse, PrefilterResult


def test_analyse_titre_banque_fermeture_score_haut():
    r = analyse({"titre": "La Société Générale ferme son agence de Rennes",
                 "texte": "L'agence de Rennes fermera le 30 juin 2026."})
    assert isinstance(r, PrefilterResult)
    assert r.score >= 3
    assert r.banks  # au moins une banque détectée
    assert r.compact_context == ""  # rempli plus tard par le pipeline


def test_analyse_phrase_banque_commune_fermeture():
    r = analyse({"titre": "Réseau bancaire",
                 "texte": "Le Crédit Agricole va fermer son agence de Tulle cet été."})
    assert r.score >= 3
    assert any("Tulle" in c for c in r.communes)


def test_analyse_liste_communes_bonus():
    r = analyse({"titre": "Crédit Agricole réorganise",
                 "texte": "Les agences de Bessines, Saint-Junien et Tulle vont fermer."})
    assert len(r.communes) >= 2
    assert r.score >= 2


def test_analyse_date_detectee():
    r = analyse({"titre": "BNP ferme une agence",
                 "texte": "La fermeture est prévue pour le 1er septembre 2026 à Lyon."})
    assert r.dates
    assert r.score >= 2


def test_analyse_adresse_detectee():
    r = analyse({"titre": "LCL ferme",
                 "texte": "L'agence LCL du 12 rue de la République, 69001 Lyon fermera."})
    assert r.addresses


def test_analyse_rh_sans_agence_penalise():
    r = analyse({"titre": "Plan social à la BNP",
                 "texte": "Suppression de postes et licenciements ; grève des salariés."})
    assert r.score <= -2, f"score={r.score}"


def test_analyse_hors_sujet_penalise():
    r = analyse({"titre": "Le marché aux fleurs ouvre", "texte": "Beau temps ce week-end."})
    assert r.score <= -3


def test_is_relevant_toujours_present():
    # compat : le booléen historique reste exposé et inchangé
    assert analyse and callable(analyse)
    from backend.prefilter import is_relevant
    assert is_relevant({"titre": "Société Générale ferme", "texte": "agence"}) is True
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_prefilter.py -k analyse -v`
Expected: FAIL (`ImportError: cannot import name 'analyse'`).

- [ ] **Step 3: Implémenter — config puis prefilter**

```python
# config.py — ajouter après TERMES_FERMETURE (bloc des mots-clés)
# Termes RH/social : servent au malus de préfiltre (-2) quand ils apparaissent
# SANS le mot "agence" (article social sans fermeture d'agence identifiée).
RH_TERMS = [
    "licenciement", "plan social", "pse", "suppression de postes", "emplois",
    "syndicat", "greve", "salaries",
]
```

```python
# backend/prefilter.py — REMPLACER tout le fichier
"""Préfiltre local (Cycle 2b) : booléen historique + scoring/entités sans IA."""
import re
import unicodedata
from dataclasses import dataclass, field

import config
from backend.drilldown import communes_candidates
from backend.extractor import normalise_banque


def _normalise(texte: str) -> str:
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn"
    )
    return sans_accents.lower()


_VARIANTES = config.ENSEIGNES + [
    v for vs in getattr(config, "MARQUES_REGIONALES", {}).values() for v in vs
]
# (forme normalisée, forme canonique) triée du plus long au plus court.
_VARIANTE_PAIRS = sorted(
    {(_normalise(v), normalise_banque(v)) for v in _VARIANTES},
    key=lambda p: len(p[0]), reverse=True,
)
_ENSEIGNES_N = [n for n, _ in _VARIANTE_PAIRS]
_TERMES_N = [_normalise(t) for t in config.TERMES_FERMETURE]
_RH_N = [_normalise(t) for t in getattr(config, "RH_TERMS", [])]

_MOIS = ("janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|"
         "septembre|octobre|novembre|decembre|décembre")
_DATE_RE = re.compile(
    r"\b\d{1,2}\s*(?:er)?\s+(?:" + _MOIS + r")\s+\d{4}\b"
    r"|\b(?:" + _MOIS + r")\s+\d{4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:courant|fin|debut|début|mi|au\s+printemps|a\s+l'automne|en)\s+\d{4}\b",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(
    r"\b\d{1,3}(?:\s*(?:bis|ter))?\s+"
    r"(?:rue|avenue|av\.?|bd|boulevard|place|impasse|route|all[ée]e|chemin|quai|cours)\b"
    r".{0,60}",
    re.IGNORECASE,
)
_DEPT_CODE_RE = re.compile(r"\((\d{2}[ab]?|2[ab])\)", re.IGNORECASE)
_SENT_SPLIT = re.compile(r"[.!?\n]+")


@dataclass
class PrefilterResult:
    score: int
    banks: list = field(default_factory=list)
    communes: list = field(default_factory=list)
    departements: list = field(default_factory=list)
    dates: list = field(default_factory=list)
    addresses: list = field(default_factory=list)
    relevant_sentences: list = field(default_factory=list)
    compact_context: str = ""


def _detect_banks(contenu_norm: str) -> list:
    found: list = []
    for norm, canon in _VARIANTE_PAIRS:
        if norm in contenu_norm and canon not in found:
            found.append(canon)
    return found


def _detect_departements(contenu: str, contenu_norm: str) -> list:
    deps: list = []
    for code, nom in config.DEPARTEMENTS.items():
        if _normalise(nom) in contenu_norm and code not in deps:
            deps.append(code)
    for m in _DEPT_CODE_RE.finditer(contenu):
        code = m.group(1)
        if code not in deps:
            deps.append(code)
    return deps


def _split_sentences(texte: str) -> list:
    return [s.strip() for s in _SENT_SPLIT.split(texte) if s.strip()]


def is_relevant(article: dict) -> bool:
    contenu = _normalise(f"{article.get('titre', '')} {article.get('texte', '')}")
    a_enseigne = any(e in contenu for e in _ENSEIGNES_N)
    a_terme = any(t in contenu for t in _TERMES_N)
    return a_enseigne and a_terme


def analyse(article: dict) -> PrefilterResult:
    titre = article.get("titre", "") or ""
    texte = article.get("texte", "") or ""
    titre_n = _normalise(titre)
    contenu = f"{titre} {texte}"
    contenu_n = _normalise(contenu)

    banks = _detect_banks(contenu_n)
    departements = _detect_departements(contenu, contenu_n)
    dates = [m.group(0) for m in _DATE_RE.finditer(contenu)]
    addresses = [m.group(0).strip() for m in _ADDRESS_RE.finditer(contenu)]

    communes: list = []
    relevant_sentences: list = []
    phrase_hit = False
    for s in _split_sentences(f"{titre}. {texte}"):
        sn = _normalise(s)
        s_bank = any(n in sn for n in _ENSEIGNES_N)
        s_term = any(t in sn for t in _TERMES_N)
        s_comm = communes_candidates(s)
        for c in s_comm:
            if c not in communes:
                communes.append(c)
        if s_bank and s_term and s_comm:
            phrase_hit = True
            relevant_sentences.append(s)
        elif s_bank or s_term:
            relevant_sentences.append(s)

    score = 0
    titre_bank = any(n in titre_n for n in _ENSEIGNES_N)
    titre_ferm = any(t in titre_n for t in _TERMES_N) or "agence" in titre_n
    if titre_bank and titre_ferm:
        score += 3
    if phrase_hit:
        score += 3
    if len(communes) >= 2:
        score += 2
    if dates:
        score += 2
    if addresses:
        score += 1

    has_term = any(t in contenu_n for t in _TERMES_N)
    if not banks and not has_term:
        score -= 3
    if _RH_N and any(r in contenu_n for r in _RH_N) and "agence" not in contenu_n:
        score -= 2

    return PrefilterResult(
        score=score, banks=banks, communes=communes, departements=departements,
        dates=dates, addresses=addresses, relevant_sentences=relevant_sentences,
    )
```

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_prefilter.py -v`
Expected: PASS (tests existants `is_relevant` + nouveaux `analyse`).

- [ ] **Step 5: Commit**

```bash
git add config.py backend/prefilter.py tests/test_prefilter.py
git commit -m "feat(2b): prefilter.analyse — scoring local + détection d'entités"
```

---

### Task 2: `context_builder.build_compact_context()`

**Files:**
- Modify: `config.py` (ajout `PREFILTER_CONTEXT_MAX_CHARS`)
- Create: `backend/context_builder.py`
- Test: `tests/test_context_builder.py`

**Interfaces:**
- Consumes: `prefilter._normalise`, `prefilter._ENSEIGNES_N`, `prefilter._TERMES_N` ; `config.PREFILTER_CONTEXT_MAX_CHARS`.
- Produces: `build_compact_context(article: dict, result, max_chars: int | None = None) -> str`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_context_builder.py
from backend.context_builder import build_compact_context
from backend.prefilter import analyse


def _ctx(article, max_chars=None):
    r = analyse(article)
    return build_compact_context(article, r, max_chars=max_chars)


def test_garde_paragraphe_pertinent_coupe_bruit():
    bruit = "La météo sera clémente ce week-end sur toute la région. " * 20
    art = {"titre": "Crédit Agricole", "source": "GN", "date": "2026-01-01", "url": "http://x",
           "texte": bruit + "\n\nLe Crédit Agricole ferme son agence de Tulle en 2026.\n\n" + bruit}
    ctx = build_compact_context(art, analyse(art), max_chars=300)
    assert "Tulle" in ctx
    assert "météo" not in ctx.lower()


def test_conserve_enumeration_communes():
    art = {"titre": "Caisse d'Épargne", "source": "MoneyVox", "date": "", "url": "",
           "texte": "Les agences de Bessines, Saint-Junien, Tulle et Guéret vont fermer."}
    ctx = build_compact_context(art, analyse(art), max_chars=4000)
    for commune in ("Bessines", "Saint-Junien", "Tulle", "Guéret"):
        assert commune in ctx


def test_respecte_max_chars():
    art = {"titre": "BNP ferme", "source": "GN", "date": "", "url": "",
           "texte": ("La BNP ferme son agence. " * 200)}
    ctx = build_compact_context(art, analyse(art), max_chars=200)
    assert len(ctx) <= 200


def test_repli_si_aucune_phrase_pertinente():
    art = {"titre": "Titre neutre", "source": "GN", "date": "", "url": "",
           "texte": "Un texte sans rien de pertinent ici."}
    ctx = build_compact_context(art, analyse(art), max_chars=4000)
    assert "Titre neutre" in ctx  # en-tête + repli sur le texte
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_context_builder.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.context_builder`).

- [ ] **Step 3: Implémenter — config puis module**

```python
# config.py — ajouter après RH_TERMS
# Contexte compact envoyé à l'IA (Cycle 2b) : plafond de caractères.
PREFILTER_CONTEXT_MAX_CHARS = int(os.getenv("PREFILTER_CONTEXT_MAX_CHARS", "8000"))
```

```python
# backend/context_builder.py — créer
"""Construction du contexte compact envoyé à l'IA (Cycle 2b, section 10).

Sélectionne les unités (paragraphes, ou phrases si un seul bloc) contenant une
banque ou un terme de fermeture, préfixe des métadonnées, et plafonne la taille.
Aucune IA, aucun réseau.
"""
from __future__ import annotations

import config
from backend.prefilter import _ENSEIGNES_N, _TERMES_N, _normalise, _split_sentences


def _est_pertinent(unite: str) -> bool:
    n = _normalise(unite)
    return any(e in n for e in _ENSEIGNES_N) or any(t in n for t in _TERMES_N)


def _entete(article: dict) -> str:
    return (
        f"TITRE: {article.get('titre', '')}\n"
        f"SOURCE: {article.get('source', '')}\n"
        f"DATE: {article.get('date', '')}\n"
        f"URL: {article.get('url', '')}\n\n"
    )


def _tronquer(texte: str, limite: int) -> str:
    if len(texte) <= limite:
        return texte
    coupe = texte[:limite]
    dernier = max(coupe.rfind("."), coupe.rfind("\n"))
    return coupe[: dernier + 1] if dernier > 0 else coupe


def build_compact_context(article: dict, result, max_chars: int | None = None) -> str:
    max_chars = max_chars or config.PREFILTER_CONTEXT_MAX_CHARS
    entete = _entete(article)
    texte = article.get("texte", "") or ""
    budget_corps = max(0, max_chars - len(entete))

    # Cas court : tout le corps tient -> on l'envoie tel quel (aucune perte).
    if len(texte) <= budget_corps:
        return _tronquer(entete + texte, max_chars)

    # Sélection des unités pertinentes.
    paragraphes = [p.strip() for p in texte.split("\n\n") if p.strip()]
    if len(paragraphes) > 1:
        unites = paragraphes
        sep = "\n\n"
    else:
        unites = _split_sentences(texte)
        sep = " "

    gardees = [u for u in unites if _est_pertinent(u)]
    corps = sep.join(gardees) if gardees else texte  # repli : texte brut

    return _tronquer(entete + corps, max_chars)
```

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python3.12 -m pytest tests/test_context_builder.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add config.py backend/context_builder.py tests/test_context_builder.py
git commit -m "feat(2b): build_compact_context — contexte compact plafonné pour l'IA"
```

---

### Task 3: Câblage `run_pipeline` (gate score + contexte compact)

**Files:**
- Modify: `config.py` (ajout `PREFILTER_MIN_SCORE`)
- Modify: `backend/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `prefilter.analyse`, `context_builder.build_compact_context`, `config.PREFILTER_MIN_SCORE`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_pipeline.py (ajouter)
def test_pipeline_score_bas_route_vigilance_sans_ia(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    # Article RH/social sans "agence" mais avec banque+terme (passe is_relevant),
    # score <= PREFILTER_MIN_SCORE -> pas d'IA, vigilance.
    art = {"titre": "Plan social à la Société Générale",
           "texte": "Suppression de postes, licenciements et grève des salariés.",
           "url": "http://rh", "date": "2026-01-10", "source": "GN", "departement": None}
    appels_ia = []
    vus = []

    def extractor_espion(a):
        appels_ia.append(a["url"])
        return None

    def vigilance_fn(a, raison):
        vus.append(raison)
        return "v1"

    pipeline.run_pipeline(conn, [lambda: [art]], extractor_espion,
                          lambda c, d: None, vigilance_fn=vigilance_fn,
                          enrich_fn=lambda u: "")
    assert appels_ia == [], "score bas -> aucun appel IA"
    assert vus and "score" in vus[0]


def test_pipeline_envoie_contexte_compact_a_l_ia(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    art = {"titre": "Société Générale ferme son agence de Rennes",
           "texte": "L'agence de Rennes fermera le 30 juin 2026.",
           "url": "http://ok", "date": "2026-01-10", "source": "GN", "departement": "35"}
    recu = []

    def extractor_espion(a):
        recu.append(a["texte"])
        return None

    pipeline.run_pipeline(conn, [lambda: [art]], extractor_espion,
                          lambda c, d: None, enrich_fn=lambda u: "")
    assert len(recu) == 1
    assert recu[0].startswith("TITRE:")  # contexte compact, pas le texte brut
    assert "Rennes" in recu[0]
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python3.12 -m pytest tests/test_pipeline.py -k "score_bas or contexte_compact" -v`
Expected: FAIL (`AttributeError: config.PREFILTER_MIN_SCORE` ou pas de gate/contexte).

- [ ] **Step 3: Implémenter — config puis pipeline**

```python
# config.py — ajouter après PREFILTER_CONTEXT_MAX_CHARS
# Gate de préfiltre : on ne saute l'IA que si le score est <= ce seuil (conservateur).
# Les articles sautés sont routés en vigilance (jamais perdus).
PREFILTER_MIN_SCORE = int(os.getenv("PREFILTER_MIN_SCORE", "-2"))
```

Modifier les imports en tête de `backend/pipeline.py` :

```python
from backend import commune_normalize, context_builder, prefilter, store, validation
```

Élever le plafond de troncature de l'enrichissement (le contexte compact fera la
compaction finale) — remplacer `[:6000]` par `[:20000]` dans le bloc d'enrichissement :

```python
                    if texte_complet:
                        art["texte"] = (texte + "\n\n" + texte_complet)[:20000]
```

Insérer, juste APRÈS le bloc d'enrichissement et AVANT le `try: resultat = extract_cached(...)` :

```python
            pf = prefilter.analyse(art)
            pf.compact_context = context_builder.build_compact_context(art, pf)
            if pf.score <= config.PREFILTER_MIN_SCORE:
                if url:
                    store.mark_url_seen(conn, url)
                if vigilance_fn and vigilance_fn(art, f"score préfiltre bas ({pf.score})"):
                    recap["vigilances"] += 1
                continue
            art["texte"] = pf.compact_context
```

Ajouter l'import de `config` en tête si absent :

```python
import config
```

- [ ] **Step 4: Lancer pour vérifier le succès (fichier puis suite complète)**

Run: `python3.12 -m pytest tests/test_pipeline.py -v`
Expected: PASS (tous, y compris les tests 2a `test_pipeline_extraction_cachee...` et `test_article_court_est_enrichi...`).

Run: `python3.12 -m pytest -q`
Expected: PASS (aucune régression).

- [ ] **Step 5: Commit**

```bash
git add config.py backend/pipeline.py tests/test_pipeline.py
git commit -m "feat(2b): câblage pipeline — gate par score + contexte compact vers l'IA"
```

---

## Self-Review (effectuée)

- **Couverture du spec** : scoring + entités (Task 1) ; contexte compact plafonné (Task 2) ; gate conservateur + vigilance + contexte compact vers l'IA (Task 3). `is_relevant` conservé (Task 1). Constantes réparties là où d'abord utilisées (`RH_TERMS` T1, `PREFILTER_CONTEXT_MAX_CHARS` T2, `PREFILTER_MIN_SCORE` T3).
- **Placeholders** : aucun ; code complet à chaque step.
- **Cohérence des types** : `PrefilterResult` (T1) consommé par `build_compact_context(article, result, max_chars)` (T2) et par le pipeline (T3) ; `_ENSEIGNES_N`/`_TERMES_N`/`_normalise`/`_split_sentences` exportés par prefilter et importés par context_builder.
- **Changements de comportement assumés** : (1) le plafond d'enrichissement passe de 6000 à 20000 pour donner de la matière à la compaction ; (2) l'IA reçoit désormais le contexte compact (préfixé `TITRE:`) au lieu du texte brut — le test 2a `test_article_court_est_enrichi_avant_extraction` reste vert car pour un article court le corps tient et est renvoyé intégralement (sentinel préservé).
- **Recall préservé** : `is_relevant` inchangé en amont ; le gate score ne rejette que `<= -2`, et route en vigilance.
