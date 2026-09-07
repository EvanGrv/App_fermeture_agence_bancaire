# 05 — Modèle de données

## Les quatre niveaux de certitude

C'est le concept central du projet. Une information sur une fermeture est
rangée au niveau le plus élevé qu'elle peut atteindre, et **descend** au lieu
de disparaître quand un critère manque.

| Niveau | Table | Ce qu'il faut pour y accéder | Visible où |
|---|---|---|---|
| **1. Carte** | `closures` | Banque + commune + date, géocodage réussi, garde d'extraction passée | Carte, tableaux |
| **2. Fermeture non géocodée** | `closures_unlocated` | Fermeture identifiée mais localisation ou preuve insuffisante | Listes départementales |
| **3. Signal départemental** | `department_signals` | « N agences dans tel département », sans nommer les communes | Vue Départements |
| **4. Vigilance** | `vigilances` | Article pertinent sans fermeture publiable | Onglet Alertes |

Un cinquième réceptacle, `vague_signals`, recueille les annonces nationales
non territorialisées (« la banque X fermera 200 agences en France »).

**Quand vous modifiez le code :** avant d'écrire un `continue` qui abandonne
une donnée, demandez-vous à quel niveau elle devrait descendre. Dans
`pipeline.py`, chaque rejet est doublé d'une écriture ailleurs — respectez ce
motif.

Le mouvement inverse existe aussi : la revue des vigilances
(`vigilance_review.py`) peut faire **remonter** une vigilance en fermeture
publiée. Les colonnes `resolved_closure_id` et `resolved_at` gardent la trace
de cette promotion.

## Le schéma SQLite

Défini dans [`backend/store.py`](../backend/store.py), créé automatiquement au
premier appel de `store.init_db()`.

### Tables de contenu

**`closures`** — les fermetures publiables (niveau 1).

| Colonne | Note |
|---|---|
| `id` | SHA-256 tronqué à 16 caractères, dérivé de banque + commune + date |
| `banque`, `commune`, `code_insee`, `departement` | `commune_originale` garde la forme d'origine avant normalisation |
| `type` | fermeture, regroupement, transformation… |
| `date_annonce`, `date_fermeture` | `date_fermeture_approx=1` si la date est approchée |
| `statut`, `statut_temporel` | `a_venir`, `passee`, `inconnu` |
| `fiabilite` | entier 0–5, dérivé de la `confidence` du modèle (×5, arrondi) |
| `lat`, `lon` | absents ⇒ la fermeture n'aurait pas dû arriver ici |
| `citation` | l'extrait de l'article qui justifie l'enregistrement |
| `evidence_level` | ex. `officiel+presse`, `presse+référentiel` |
| `service_impact`, `point_postal_avant/apres`, `postal_point_id` | spécifiques au canal La Banque Postale |

**`sources`** — les articles justifiant une fermeture. Relation N-N contrainte
par `UNIQUE(closure_id, url)` : une même fermeture peut être corroborée par
plusieurs articles, et c'est souhaitable.

**`closures_unlocated`**, **`department_signals`**, **`vague_signals`**,
**`vigilances`** — les niveaux 2 à 4. Chacune porte la `raison` de sa
présence à ce niveau, ce qui rend le tri débogable.

### Tables de travail

| Table | Rôle |
|---|---|
| `seen_urls` | Déduplication. Le retrait d'une URL force son retraitement |
| `articles` | Cache fulltext : `raw_url`, `canonical_url`, `fulltext`, `fulltext_hash`, `fetch_status` |
| `extractions` | Cache IA, clé `(content_hash, extraction_version, model)`, avec `attempts` et `retry_after` |
| `referentiel` | Agences connues (OpenStreetMap + LBP), clé `osm_id` |
| `controles_sirene` | État administratif par fermeture |
| `vigilance_reviews` | Journal des revues, pour appliquer le cooldown |

## Le format de `data/export/data.json`

Généré par `export.build_payload()`. C'est le **contrat d'interface** avec le
frontend : toute modification doit être répercutée dans `frontend/app.js`.

```jsonc
{
  "generated_at": "2026-08-05T06:20:59+00:00",
  "enseignes": [ ... ],              // banques présentes, pour les filtres
  "departements": { "01": {...} },   // agrégats par département
  "department_estimates": { ... },   // estimations issues des signaux
  "regions": [ ... ],
  "closures": [ ... ],               // niveau 1 — la carte
  "closures_unlocated": [ ... ],     // niveau 2
  "department_signals": [ ... ],     // niveau 3
  "vague_signals": [ ... ],
  "vigilances": [ ... ],             // niveau 4
  "plans": [ ... ]                   // plans multi-agences détectés
}
```

Ordres de grandeur à l'export du 5 août 2026 : 174 fermetures cartographiées,
227 non géocodées, 16 signaux départementaux, 109 signaux vagues, 1 599
vigilances. **Le rapport entre les niveaux est normal** : la carte est stricte
par conception, et l'essentiel du volume reste en vigilance.

## Les autres fichiers de `data/`

| Chemin | Versionné | Contenu |
|---|---|---|
| `data/export/data.json` | oui | Le payload ci-dessus, consommé par le front |
| `data/export/fermetures_nettoyees.csv` | oui | Les fermetures à plat, pour Excel |
| `data/export/departements.geojson` | oui | Contours des départements |
| `data/export/extraction_audit.{csv,json}` | oui | Anomalies détectées à l'export |
| `data/export/copilot_coverage.{csv,json}` | oui | Sortie du benchmark de couverture |
| `data/seeds/pqr_mairies_sources.csv` | oui | Sources PQR et mairies de référence |
| `data/seeds/reference_copilot_2026.xlsx` | oui | Fichier de référence pour le benchmark et `--seed-excel` |
| `data/press.db` | **non** | Base de travail, reconstructible |
| `data/cache/` | **non** | Cache HTTP et fulltext |

## Faire évoluer le schéma

`store.init_db()` exécute le schéma en `CREATE TABLE IF NOT EXISTS`, puis
appelle `_ensure_closures_columns()` et `_ensure_resolution_columns()`, qui
comparent les colonnes présentes (`PRAGMA table_info`) au jeu attendu et
ajoutent les manquantes par `ALTER TABLE`. C'est idempotent, mais il n'y a
**pas de système de migration versionné**.

Pour ajouter une colonne : l'ajouter au `CREATE TABLE` du schéma **et** à la
liste de la fonction `_ensure_*` correspondante — les deux, sinon les bases
existantes (celle du cache GitHub Actions, notamment) ne se mettront pas à
niveau. Une colonne supprimée ou
renommée n'a **aucun chemin de migration** — c'est une limite réelle du projet,
à traiter à la main si le cas se présente.
