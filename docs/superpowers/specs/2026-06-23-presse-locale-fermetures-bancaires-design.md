# Veille presse — Fermetures d'agences bancaires par département

**Date :** 2026-06-23
**Statut :** Design validé

## 1. Objectif

Construire un système qui collecte la presse locale et les sources officielles
pour donner une vision, par département, des agences bancaires qui vont fermer
ou fusionner en France.

Livrables, par ordre de priorité :

1. Un **tableau de bord + carte interactive** (front web sur-mesure, Leaflet)
   adossé à une **base de données**.
2. Plus tard : un **rapport hebdomadaire par email** s'appuyant sur la même base.

## 2. Périmètre

- **Banques :** toutes les enseignes à réseau d'agences (Crédit Agricole, BNP
  Paribas, Société Générale, groupe BPCE — Banque Populaire / Caisse d'Épargne,
  Crédit Mutuel / CIC, LCL, La Banque Postale, etc.).
- **Géographie :** tous les départements de France.
- **Signaux capturés :** **fermetures** d'agences **et fusions/regroupements**
  (souvent une fermeture déguisée). Les réductions d'horaires / passages sans
  personnel sont hors périmètre pour cette première version (possibilité
  d'élargir ensuite).
- **Temporalité :** priorité aux fermetures à venir (annoncées), mais on
  conserve aussi les fermetures récentes confirmées, distinguées par un statut.

## 3. Choix structurants

- **Exécution :** Python en local, lancé à la demande (l'utilisateur est à
  l'aise avec le code). Pas de serveur 24/7.
- **Architecture :** deux blocs indépendants reliés par un fichier d'export.
  - Backend Python = collecte → filtrage → extraction → stockage → export.
  - Frontend = page web statique (HTML/JS + Leaflet) qui lit l'export.
- **Extraction :** par IA (API Claude), précédée d'un pré-filtre par mots-clés
  pour limiter le coût.
- **Coût :** gratuit hors API Claude (sources et géocodage gratuits).

## 4. Architecture & flux de données

```
BACKEND (Python, lancé à la demande)
  1. COLLECTE (3 sources)
     - Presse régionale / actus  -> Google News RSS (par département + mots-clés)
     - Agrégateur                -> GDELT (gratuit, API)
     - Officiel                  -> Registre ACPR/Banque de France (REGAFI) + sites corpo
  2. PRÉ-FILTRE (mots-clés)       -> écarte le bruit avant l'IA
  3. EXTRACTION IA (API Claude)   -> JSON structuré par article
  4. DÉDUPLICATION + STOCKAGE     -> SQLite (1 fermeture = 1 enregistrement)
  5. GÉOCODAGE (API BAN, gratuit) -> lat/lon par commune
  6. EXPORT                       -> data.json + departements.geojson

FRONTEND (page web statique)
  Carte Leaflet (choroplèthe par département) + liste filtrable
  Filtres : banque, type, période, fiabilité, département
  Clic sur un point -> détail + lien vers l'article source
```

Principe directeur : le backend produit un `data.json` propre ; le frontend ne
fait que l'afficher. Les deux évoluent séparément. Le futur rapport email lira
la même base SQLite.

## 5. Composants

```
press_local/
├── backend/
│   ├── collectors/
│   │   ├── google_news.py   # RSS Google News : requêtes par département × mots-clés
│   │   ├── gdelt.py         # API GDELT : articles FR filtrés banque/fermeture
│   │   └── official.py      # Registre ACPR (REGAFI) + pages corpo des réseaux
│   ├── prefilter.py         # garde un article si mots-clés pertinents présents
│   ├── extractor.py         # API Claude -> JSON {banque, commune, dept, type, date, fiabilité, citation}
│   ├── dedup.py             # fusionne les doublons (même banque+commune+type sur fenêtre de dates)
│   ├── store.py             # lecture/écriture SQLite
│   ├── geocode.py           # API Base Adresse Nationale -> lat/lon (avec cache)
│   ├── export.py            # SQLite -> data.json + departements.geojson
│   └── run.py               # orchestre tout le pipeline (1 commande)
├── frontend/
│   ├── index.html
│   ├── app.js               # Leaflet, filtres, panneau de détail
│   └── style.css
├── data/
│   ├── press.db             # SQLite
│   ├── cache/               # cache géocodage + articles déjà vus
│   └── export/data.json
├── config.py                # mots-clés, liste des enseignes, départements, clé API
└── requirements.txt
```

Responsabilités :

- **collectors** — chaque collecteur renvoie une liste normalisée d'articles
  bruts `{titre, texte, url, date, source, departement?}`. Interchangeables :
  on peut en ajouter/retirer un sans toucher au reste.
- **prefilter** — barrière économique : ne laisse passer à l'IA que les articles
  contenant à la fois un nom d'enseigne **et** un terme de fermeture/fusion.
- **extractor** — qualité du système. Renvoie un score de **fiabilité**, le
  **statut** (confirmé / projet / rumeur) et la **phrase justificative** extraite
  de l'article. Sortie validée contre un schéma JSON.
- **dedup** — clé de déduplication déterministe (banque + commune + type) sur
  une fenêtre de dates ; corrobore une fermeture par plusieurs sources.
- **store / geocode / export** — persistance SQLite, géocodage caché via la Base
  Adresse Nationale, export JSON + GeoJSON pour le front.

## 6. Modèle de données

### Table `closures`

| Champ | Type | Description |
|---|---|---|
| `id` | TEXT | identifiant unique (hash banque+commune+type) |
| `banque` | TEXT | enseigne normalisée |
| `commune` | TEXT | commune concernée |
| `code_insee` | TEXT | code commune (fiabilise le géocodage) |
| `departement` | TEXT | code département (ex. « 35 ») |
| `type` | TEXT | `fermeture` \| `fusion` |
| `date_annonce` | DATE | date de l'article/annonce |
| `date_fermeture` | DATE | date prévue de fermeture (NULL si inconnue) |
| `statut` | TEXT | `confirmé` \| `projet` \| `rumeur` |
| `fiabilite` | INTEGER | score 1–5 donné par l'IA |
| `lat` / `lon` | REAL | coordonnées (géocodage) |
| `citation` | TEXT | phrase justificative extraite de l'article |
| `created_at` | DATETIME | date d'insertion |

### Table `sources` (relation 1→N)

| Champ | Type | Description |
|---|---|---|
| `id` | INTEGER | clé |
| `closure_id` | TEXT | → `closures.id` |
| `url` | TEXT | lien vers l'article |
| `titre` | TEXT | titre de l'article |
| `source` | TEXT | ex. « Ouest-France », « GDELT », « ACPR » |
| `date` | DATE | date de publication |

**Déduplication :** une même fermeture annoncée par 3 journaux = 1 ligne
`closures` + 3 lignes `sources`. Plus une fermeture a de sources, plus la
fiabilité monte.

## 7. Robustesse & qualité

- **Collecte résiliente** : une source en panne est loguée et n'interrompt pas
  le run ; les autres sources continuent.
- **Idempotence** : `run.py` relançable sans créer de doublons (cache des URLs
  déjà traitées + clé de dédup déterministe).
- **Reprise** : articles bruts stockés avant l'extraction IA ; un échec API ne
  force pas un re-téléchargement complet.
- **Garde-fous IA** : sortie validée contre un schéma. En cas d'invalidité ou
  d'incertitude (commune introuvable, banque inconnue), l'enregistrement va dans
  une zone « à vérifier » plutôt que d'être inséré directement.
- **Coûts** : pré-filtre strict + cache => aucun article envoyé deux fois à l'API.
- **Géocodage** : mis en cache ; échec => l'agence reste en base, listée « sans
  position ».

## 8. Tests (TDD)

- **Unitaires** sur la logique pure : pré-filtre, dédup, normalisation des noms
  d'enseignes.
- **Extracteur** testé sur des articles réels figés (fixtures), sans appel API.
- **Collecteurs** testés contre des réponses réseau enregistrées (pas d'appel
  réseau réel en test).
- Construction en test-d'abord lors de l'implémentation.

## 9. Hors périmètre (v1)

- Réductions d'horaires / agences sans personnel / transformation en DAB.
- Rapport email hebdomadaire (phase 2, lira la même base SQLite).
- Serveur/collecte 24/7 (exécution à la demande uniquement).

## 10. Dépendances externes

- **API Claude (Anthropic)** — extraction structurée (clé API requise).
- **Google News RSS** — gratuit, sans clé.
- **GDELT** — gratuit, sans clé.
- **Registre ACPR / REGAFI** — données publiques.
- **Base Adresse Nationale (BAN)** — géocodage gratuit, sans clé.
- **Leaflet** — cartographie front, gratuit.
