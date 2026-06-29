# Base de preuve nationale des fermetures d'agences — Design

Date : 2026-06-29
Statut : approuvé (direction) — spec détaillé limité au **Cycle 1**.

## Vision

On ne construit pas seulement une carte, mais une **base de preuve hiérarchisée**.
Copilot / ChatGPT / Claude sont les minimums à battre : on doit retrouver tout ce
qui est fiable chez eux **et** produire des cas supplémentaires.

### Principes directeurs (transverses, non négociables)

1. **Aucune information ne disparaît faute d'adresse.** Elle descend au bon niveau :
   point carte précis → fermeture non géocodée (commune) → signal départemental →
   vigilance vague. Jamais jetée silencieusement.
2. **La carte reste stricte.** On ne publie *jamais* automatiquement les résultats
   faibles comme points sur la carte. La carte = points précis et fiables.
   La base, elle, devient large et profonde.
3. **Toute ligne Copilot doit être expliquée** : retrouvée, confirmée, ou rejetée
   avec une raison. Aucune ligne inexpliquée.

## État de l'existant (pipeline déjà en place)

Le dépôt `press_local` implémente déjà une grande partie du périmètre :

| Brique | Module existant |
|---|---|
| Comparaison référence interne | `tools/compare_expected_closures.py` |
| Scoring de fiabilité des sources | `backend/source_tier.py` |
| Préfiltre local | `backend/prefilter.py` |
| Extraction IA Haiku + fallback | `backend/extractor.py`, `backend/openai_fallback.py` |
| Explosion de plans multi-agences | `backend/drilldown.py` (`est_plan`) |
| Génération de requêtes | `backend/query_builder.py` |
| Revue arborescente des vigilances | `backend/vigilance_review.py` |
| Stockage (closures + vigilances) | `backend/store.py` |
| Vue départementale + carte | `backend/drilldown.py`, `frontend/app.js` |
| Export | `backend/export.py` → `data/export/data.json` |

L'export `data.json` expose déjà trois niveaux exploitables :
`closures` (précis, avec `lat`/`lon`), `department_estimates` (signaux
départementaux), `vigilances` (vague). Le cahier des charges est donc une
**évolution** de l'existant, pas un greenfield.

## Feuille de route — 5 cycles courts et mesurables

Chaque cycle a son propre spec → plan → implémentation.

- **Cycle 1 (ce spec)** — Benchmark Copilot complet : comparateur, fichier
  d'overrides, rapport de couverture, **aucune ligne Copilot inexpliquée**.
- **Cycle 2** — Fulltext systématique + cache ; préfiltrage local ; extraction
  article-liste avec Haiku ; fallback Sonnet uniquement sur ambigu.
- **Cycle 3** — Stockage multi-niveaux explicite : points carte précis /
  fermetures non géocodées / signaux départementaux / vigilances vagues.
- **Cycle 4** — Scan national par département ; rapport de couverture
  départemental ; priorité aux départements/sources déjà signalés.
- **Cycle 5** — Comparaison finale avec Copilot : retrouver tout le fiable +
  produire des cas supplémentaires. Sinon la recherche n'est pas assez profonde.

---

# Cycle 1 — Benchmark Copilot (spec détaillé)

## But

Pour **chaque** ligne du fichier Copilot, produire une explication non ambiguë de
sa présence/absence dans le pipeline, avec une action suivante concrète. C'est le
baromètre permanent « battre Copilot ».

Fichier de référence : `liste_agences_bancaires_fermetures_a_partir_2026_v4_CE_complement.xlsx`
(racine du dépôt). 76 lignes de données, 17 colonnes.

## Architecture

Nouveau module `tools/compare_copilot_coverage.py`, **réutilisant** les helpers
de `tools/compare_expected_closures.py` et `backend/` (pas de réécriture) :
- `backend.dedup.normalise_cle`, `_cle_banque`, `_cle_commune` (normalisation
  banque/commune, gère tirets/apostrophes, Crédit Municipal, enseignes).
- `backend.drilldown.est_plan` (détection plan multi-agences, utile pour
  `next_action`).
- Chargement xlsx mutualisé (lecture openpyxl read-only, data_only).

Le module existant `compare_expected_closures.py` reste **inchangé** (sémantique
interne distincte). On factorise au besoin les helpers communs sans modifier son
comportement ni ses tests.

## Entrées

1. **Excel Copilot.** Colonnes (index → champ) :
   - `[0]` (en-tête littéral `²`) → **banque**
   - `[1]` Agence / localisation
   - `[2]` Adresse la plus complète possible
   - `[3]` Commune
   - `[4]` Département
   - `[5]` Région
   - `[6]` Latitude, `[7]` Longitude
   - `[8]` Date de fermeture, `[9]` Précision date
   - `[10]` Source principale, `[11]` Lien source
   - `[12]` Sources de localisation, `[13]` Lien localisation
   - `[14]` Score confiance, `[15]` Statut, `[16]` Commentaires

   Le mapping est **positionnel par défaut** (l'en-tête banque est `²`), avec
   repli sur les alias d'en-têtes français quand les positions diffèrent.

2. **`data/export/data.json`** (paramétrable `--payload`) : `closures`,
   `department_estimates`, `departements`, `vigilances`.

3. **`tools/copilot_overrides.yaml`** (optionnel, versionné). Liste de verdicts
   humains. Chaque entrée :
   ```yaml
   - match:            # clé stable d'identification de la ligne Copilot
       banque: "BNP Paribas"
       commune: "Chalon-sur-Saône"
       agence_localisation: "Chalon-sur-Saône - avenue de Paris"  # optionnel
     status: rejected_with_reason   # ou confirmed_missing / present_*
     missing_reason: "ADCF sans URL — non vérifiable avant publication carte"
     next_action: "Rechercher source primaire commune avant toute publication"
   ```
   La clé de match est normalisée via `_cle_banque`/`_cle_commune`. Si
   `agence_localisation` est fourni il précise le match ; sinon `banque`+`commune`
   suffisent. Les overrides **forcent** `status`/`missing_reason`/`next_action`.

## Sorties

- `data/export/copilot_coverage.csv` et `data/export/copilot_coverage.json` :
  une ligne par ligne Copilot, avec tous les champs ci-dessous.
- Récapitulatif console (compte par `status`, taux de couverture, lignes
  inexpliquées = 0 attendu).

Champs émis par ligne :

| Champ | Source |
|---|---|
| `banque`, `agence_localisation`, `commune`, `departement`, `adresse`, `lat`, `lon`, `source`, `url`, `score_copilot`, `statut_copilot` | Excel Copilot |
| `matched_pipeline` | oui / non |
| `match_type` | exact / commune / département / aucun |
| `pipeline_id` | id de la closure matchée, sinon vide |
| `pipeline_status` | `statut`/`statut_temporel` de la closure matchée |
| `status` | un des 6 (voir ci-dessous) |
| `missing_reason` | raison textuelle (auto ou override) |
| `next_action` | action concrète (requêtes ciblées pour `needs_research`) |

## Cascade de classification

Les **overrides s'appliquent d'abord** ; sinon auto-classification depuis
`data.json` :

1. Closure matchée (banque + commune, ou banque + `agence_localisation`, ou
   banque + adresse) **avec `lat`+`lon`** → `present_on_map`.
   - `match_type = exact` si l'adresse ou la proximité lat/lon concordent
     (haversine < 500 m entre point Copilot et point pipeline) ; sinon `commune`.
2. Closure matchée **sans `lat`/`lon`** → `present_unlocated`, `match_type=commune`.
3. Pas de closure, mais `department_estimates`/`departements` portent un signal
   pour (banque, département) → `present_department`, `match_type=département`.
4. Rien nulle part → `needs_research`, `match_type=aucun`.
   `next_action` = liste concrète de requêtes (section 6 du cahier des charges) :
   `"{banque}" "{commune}" "fermeture agence"`,
   `"{banque}" "{commune}" "agence ferme"`,
   `"{banque}" "{commune}" "regroupement agence"`, etc.
   (limitée à ~5 requêtes ; `est_plan` ajoute une requête « plan » si pertinent).
5. `rejected_with_reason` / `confirmed_missing` : **uniquement via overrides**
   (jugement humain), `missing_reason` obligatoire.

Garantie : tout `status` ∈ {present_on_map, present_unlocated, present_department,
needs_research, rejected_with_reason, confirmed_missing}. Pas de valeur vide.

## Matching — détails

- Banque : `_cle_banque` (normalise enseignes, Crédit Municipal).
- Commune : `_cle_commune` (insensible tirets/apostrophes/espaces).
- Un row Copilot matche une closure si même banque **et** une de ces communes
  concorde : `closure.commune`, `closure.agence_localisation`,
  `closure.commune_originale`.
- Corroboration adresse : si la closure a une `adresse` et le row Copilot aussi,
  une concordance de numéro+voie renforce `exact` (best-effort, non bloquant).
- Corroboration géo : haversine(lat/lon Copilot, lat/lon closure) < 500 m → `exact`.

## Tests (TDD — écrits avant l'implémentation)

`tests/test_compare_copilot_coverage.py` :
1. Header `²` (col 0) correctement mappé sur banque.
2. Row → `present_on_map` quand closure avec lat/lon matche (exact via proximité).
3. Row → `present_unlocated` quand closure sans lat/lon matche.
4. Row → `present_department` quand seul un department_estimate matche.
5. Row → `needs_research` quand rien ne matche, avec `next_action` non vide
   contenant des requêtes.
6. Override → force `rejected_with_reason` + `missing_reason`.
7. **Invariant clé** : sur un échantillon, aucune ligne sans `status`
   (aucune ligne inexpliquée).
8. Chargement de l'Excel réel : 76 lignes, toutes classées.

Fixtures : un petit `.xlsx` généré (openpyxl) + un `data.json` minimal couvrant
les 6 cas + un `copilot_overrides.yaml` minimal.

## CLI

```bash
python -m tools.compare_copilot_coverage \
    liste_agences_bancaires_fermetures_a_partir_2026_v4_CE_complement.xlsx \
    --payload data/export/data.json \
    --overrides tools/copilot_overrides.yaml \
    --out-dir data/export
```

Sans `--overrides`, fonctionne en auto-classification pure (les statuts manuels
restent simplement inutilisés). Affiche le récap et écrit les deux fichiers.

## Hors périmètre Cycle 1 (réservé aux cycles suivants)

- Lancer effectivement les recherches `next_action` (Cycle 4).
- Refonte du stockage en tiers explicites (Cycle 3).
- Fulltext/préfiltre/extraction article-liste (Cycle 2).
- Modification du frontend / de la carte (Cycle 3+).
