# Cycle 2b — Préfiltre local scoring + détection d'entités + contexte compact (Design)

Date : 2026-07-01
Statut : approuvé sur le principe. Spec détaillé d'un sous-cycle (sections 9-10).

## Contexte

Sous-cycle du Cycle 2 (voir [2a](2026-06-30-cycle2a-fulltext-cache-design.md), fait).
Ordre : **2a fulltext/cache (fait) → 2b préfiltre+contexte (ce spec) → 2c extraction Haiku nouveau schéma**.

Aujourd'hui le préfiltre ([backend/prefilter.py](../../../backend/prefilter.py)) est un
booléen `is_relevant(article)` = (une enseigne présente) ET (un terme de fermeture
présent), utilisé comme gate dans `pipeline.py` et `vigilance.py`. Le pipeline
envoie ensuite à l'IA le `texte` brut tronqué à 6000 caractères.

Objectif transverse : « lire beaucoup, payer peu de tokens » **sans jamais perdre
une info** (une info faible descend en vigilance, elle n'est pas jetée).

## But

1. Remplacer le booléen par un **scoring local sans IA** + détection d'entités
   (banques, communes candidates, départements, dates, adresses) + extraction des
   phrases pertinentes.
2. Construire un **contexte compact** (paragraphes pertinents + voisinage) envoyé
   à l'IA à la place du texte brut tronqué → moins de tokens.
3. Gate **conservateur** : ne sauter l'IA que sur les cas clairement faibles, et
   router les sautés en **vigilance** (jamais perdus).

## Périmètre

- **2b couvre** : `analyse()` (score + entités + phrases), `build_compact_context()`,
  câblage pipeline (gate par score + contexte compact vers l'IA), constantes config.
- **2b ne couvre PAS** : détection INSEE précise des communes (résolution INSEE via
  `geocode`/BAN post-IA, inchangée) ; le nouveau schéma d'extraction (2c) ; le scan
  national (Cycle 4).
- **Détection communes** : heuristique noms propres (pas de dataset embarqué).
- **Compat** : `is_relevant(article) -> bool` **conservé** (dérivé), pour ne rien
  casser dans `vigilance.py` ni ailleurs.

## Architecture / fichiers

- **Modify** `backend/prefilter.py` : ajoute `PrefilterResult` + `analyse(article)`.
  `is_relevant` conservé (réimplémenté en `bool(banks) and bool(termes)` comme
  aujourd'hui). Réutilise les helpers existants pour rester DRY :
  `drilldown._detecter_banque`, `drilldown.communes_candidates`,
  `drilldown._DATE_PLAN`/`date_commune_du_plan`.
- **Create** `backend/context_builder.py` : `build_compact_context(article, result, max_chars)`.
- **Modify** `backend/pipeline.py` : après enrichissement, calcule `analyse(art)`,
  gate par score, envoie le contexte compact à l'IA.
- **Modify** `config.py` : `PREFILTER_MIN_SCORE` (défaut `-2`),
  `PREFILTER_CONTEXT_MAX_CHARS` (défaut `8000`).

## `PrefilterResult` (dataclass)

```python
@dataclass
class PrefilterResult:
    score: int
    banks: list[str]              # enseignes/marques détectées (normalisées)
    communes: list[str]           # candidats noms propres (non validés INSEE)
    departements: list[str]       # noms config.DEPARTEMENTS ou codes "(dd)"
    dates: list[str]              # mentions de dates détectées
    addresses: list[str]          # motifs d'adresse "N° voie … CP"
    relevant_sentences: list[str] # phrases contenant banque/commune/fermeture
    compact_context: str          # rempli par build_compact_context (section 10)
```

`analyse()` remplit tout sauf `compact_context` (laissé vide ; le pipeline appelle
ensuite `build_compact_context`). Ce découpage garde `analyse` (section 9) et la
compaction (section 10) testables indépendamment.

## Scoring local (section 9)

Sur le texte normalisé (`titre` + `texte`), sans IA :

| Règle | Points |
|---|---|
| titre contient une banque **et** (fermeture **ou** agence) | +3 |
| une phrase contient banque **et** commune-candidate **et** terme de fermeture | +3 |
| liste de communes détectée (≥ 2 candidats) | +2 |
| date de fermeture détectée | +2 |
| adresse détectée | +1 |
| hors sujet évident (ni banque ni terme) | -3 |
| RH/social sans « agence » (termes RH présents ET « agence » absent) | -2 |

Termes RH (déclencheurs du -2) : `licenciement, plan social, pse, suppression de
postes, emplois, syndicat, grève, salariés` (liste dans `config`, extensible).
Le score final est la somme (peut être négatif). La règle -3 ne se déclenche
quasi jamais dans le pipeline (déjà filtré par `is_relevant`) mais rend `analyse`
utilisable de façon autonome.

## Détection d'entités (heuristique, réutilise l'existant)

- **banques** : matching enseignes + marques régionales (via `_detecter_banque`,
  étendu pour renvoyer *toutes* les occurrences).
- **communes** : `drilldown.communes_candidates` (noms propres, énumérations).
- **départements** : noms de `config.DEPARTEMENTS` présents, ou motif `\((\d{2}|2[ab])\)`.
- **dates** : regex — `1er septembre 2026`, ISO `2026-09-01`, `courant 2025`,
  `fin 2025`, `au printemps 2025`.
- **adresses** : regex `\d{1,3}\s+(rue|avenue|av|bd|boulevard|place|impasse|route|
  allée|chemin)\b.*?\b\d{5}\b` (best-effort).

## Contexte compact (section 10) — `build_compact_context`

Construit une chaîne compacte pour l'IA :
1. En-tête : `TITRE`, `SOURCE`, `DATE`, `URL` (métadonnées de l'article).
2. Corps : les **paragraphes** contenant au moins une `relevant_sentence`, chacun
   accompagné de ± 2 phrases de voisinage ; les énumérations/listes de communes
   sont conservées entières (utile pour les articles-listes).
3. Dédoublonnage des paragraphes, ordre d'apparition préservé.
4. Plafond `max_chars` (défaut `PREFILTER_CONTEXT_MAX_CHARS = 8000`) : troncature
   propre à la dernière phrase entière sous la limite.
5. Repli : si aucune phrase pertinente (cas rare post-gate), renvoyer
   `titre + texte` tronqué à `max_chars` (comportement proche de l'actuel).

## Câblage pipeline (gate conservateur)

Ordre dans `run_pipeline`, par article ayant passé `is_relevant` puis enrichi
(fulltext systématique de 2a) :

1. `result = prefilter.analyse(art)` sur le texte **enrichi**.
2. `result.compact_context = context_builder.build_compact_context(art, result, PREFILTER_CONTEXT_MAX_CHARS)`.
3. **Gate score** : si `result.score <= config.PREFILTER_MIN_SCORE` (défaut `-2`) →
   **ne pas** appeler l'IA ; router en vigilance
   (`vigilance_fn(art, f"score préfiltre bas ({result.score})")`) ; continuer.
   L'info n'est jamais perdue.
4. Sinon : `art["texte"] = result.compact_context` puis extraction via
   `extract_cached(art, extractor_fn, conn)` (2a). Le `content_hash` porte donc
   sur le contexte compact (déterministe, stable).

`is_relevant` reste le filtre de périmètre en amont (rappel préservé) ; le score
n'ajoute qu'un rejet **conservateur** des cas clairement faibles (RH/social sans
agence, hors sujet), tous routés en vigilance.

## Gestion d'erreurs

- `analyse` et `build_compact_context` sont purs et best-effort (aucune exception
  propagée ; regex tolérantes ; entrées vides → score 0, contexte = repli).
- Aucune écriture DB dans ces modules (calcul pur) ; le pipeline gère le routage.

## Tests (TDD)

`tests/test_prefilter.py` (étendre) :
1. `is_relevant` inchangé : tous les tests existants passent.
2. `analyse` : titre banque+fermeture → `score >= 3`, `banks` non vide.
3. phrase banque+commune+fermeture → `+3` et `communes` non vide.
4. liste de communes (≥2) → `+2`.
5. date de fermeture détectée → `+2`, `dates` non vide.
6. adresse détectée → `+1`, `addresses` non vide.
7. RH/social sans « agence » → `score <= -2` malgré une banque citée.
8. hors sujet (ni banque ni terme) → `-3`.

`tests/test_context_builder.py` (créer) :
9. garde les paragraphes pertinents + voisinage, coupe le bruit.
10. conserve une énumération de communes (article-liste).
11. respecte `max_chars` (troncature à la phrase entière).
12. repli si aucune phrase pertinente.

`tests/test_pipeline.py` (étendre) :
13. article `score <= PREFILTER_MIN_SCORE` → pas d'appel IA, vigilance créée.
14. article normal → `art["texte"]` reçu par l'extracteur == contexte compact
    (espion sur l'extracteur).

Fixtures : dicts d'articles en clair ; espions sur `extractor_fn`/`vigilance_fn`.

## Critères de réussite 2b

- Le pipeline envoie à l'IA un contexte compact (≤ `PREFILTER_CONTEXT_MAX_CHARS`),
  pas le texte brut tronqué.
- Les articles clairement faibles (RH/social sans agence) ne consomment pas d'IA
  mais restent visibles en vigilance.
- `is_relevant` inchangé ; aucun test existant cassé.
