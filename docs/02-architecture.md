# 02 — Architecture

## Ce que fait l'application

Elle constitue une **base de preuve nationale des fermetures et regroupements
d'agences bancaires en France**, à partir de la presse locale et de sources
officielles, et la publie sous forme de carte et de tableaux.

Ce n'est pas seulement une carte : c'est une base hiérarchisée où chaque
information est rangée au niveau de certitude qu'elle mérite. Une fermeture
nominative et datée finit sur la carte ; une rumeur syndicale finit en
vigilance. Les deux sont conservées.

## Vue d'ensemble

Le projet est un **batch hors ligne** qui produit un fichier JSON, plus un
**frontend statique** qui l'affiche. Il n'y a pas de serveur applicatif en
production, pas de base de données hébergée, pas d'authentification.

```
   SOURCES                    TRAITEMENT                   PUBLICATION
┌──────────────┐        ┌────────────────────┐        ┌─────────────────┐
│ Google News  │        │                    │        │                 │
│ RSS locaux   │        │  run.py            │        │ data/export/    │
│ MediaCloud   │───────▶│    │               │───────▶│   data.json     │
│ EventRegistry│        │    ▼               │        │   *.csv         │
│ GDELT        │        │  backend/          │        │   departements  │
│ Common Crawl │        │    pipeline.py     │        │     .geojson    │
│ Légifrance   │        │                    │        │                 │
│ La Poste API │        │    ▼               │        └────────┬────────┘
│ Recherche web│        │  data/press.db     │                 │
└──────────────┘        │  (SQLite, local)   │                 ▼
                        └────────────────────┘        ┌─────────────────┐
                                                      │ frontend/       │
                        ┌────────────────────┐        │  index.html     │
                        │ OpenAI / Anthropic │        │  app.js         │
                        │ (extraction)       │        │  (Leaflet)      │
                        └────────────────────┘        └─────────────────┘
                                                               │
                                                      Vercel (statique)
```

Le point important : **SQLite est un artefact de travail, pas la base de
production.** Ce qui est publié, c'est `data/export/data.json`, versionné dans
Git et servi par Vercel. La base `press.db` vit dans le cache GitHub Actions
d'un run à l'autre.

## Les composants

### `run.py` — l'orchestrateur

Le point d'entrée unique. Il enchaîne, dans l'ordre : configuration de la
fenêtre temporelle, ouverture de la base, quarantaine des anciens marqueurs
LBP, synchronisation du réseau officiel La Poste, appel de `run_pipeline`,
ingestion des fermetures SG vérifiées, chargement du référentiel d'agences,
signaux Légifrance, éclatement des plans multi-agences, revue des vigilances,
contrôles SIRENE, puis export.

Il ne contient presque aucune logique métier : il câble les composants entre
eux et affiche la progression. La logique est dans `backend/`.

### `backend/pipeline.py` — le cœur

`run_pipeline()` est la boucle qui transforme des articles bruts en
enregistrements. C'est le fichier à lire en premier pour comprendre le projet.
Détail complet dans [03-pipeline.md](03-pipeline.md).

### `backend/collectors/` — les entrées

Un module par source. Tous exposent la même fonction `collect()` renvoyant une
liste de dictionnaires d'articles. **Un collecteur qui échoue n'interrompt
jamais le run** : l'exception est capturée et le run continue avec les autres.
Détail dans [04-sources.md](04-sources.md).

### `backend/extractor.py` — l'extraction IA

Envoie le contexte compact d'un article à un modèle et récupère une structure
validée par Pydantic : type d'article, fermetures détectées, signaux
départementaux, signaux vagues, confiance. C'est le seul endroit où l'IA
intervient dans le flux principal.

`backend/openai_fallback.py` fournit l'implémentation OpenAI ; le choix entre
les deux fournisseurs se fait par `EXTRACTION_PROVIDER`, sans changement de
code.

### `backend/store.py` — la persistance

Tout l'accès SQLite. Le schéma complet est décrit dans
[05-modele-de-donnees.md](05-modele-de-donnees.md). C'est le plus gros fichier
du projet (907 lignes) et le point de passage obligé de toute écriture.

### `backend/export.py` — la sortie

`build_payload()` assemble le JSON consommé par le frontend, et
`export_fermetures_csv()` produit le tableau à plat. Toute modification du
format de `data.json` doit être répercutée dans `frontend/app.js`.

### `frontend/` — l'affichage

Trois fichiers, sans framework ni build : `index.html`, `app.js` (2 040
lignes), `style.css`. Cartographie par Leaflet. Voir
[06-frontend.md](06-frontend.md).

### `app_server.py` — le serveur de développement

Un serveur HTTP minimal qui sert les fichiers statiques **et** expose
`/api/pipeline/run`, `/api/pipeline/status/<id>` et `/api/pipeline/jobs` pour
déclencher un run depuis l'onglet Paramètres. Il n'est **pas** déployé en
production — Vercel ne sert que du statique.

### `tools/` — l'outillage de diagnostic

Scripts hors flux principal, lancés à la main. Ils sont en **lecture seule** :
aucun n'écrit dans la base ni ne crée de fermeture.

```bash
# Benchmark de couverture : classe chaque ligne du fichier de référence sur
# deux axes (couverture dans notre base, fiabilité de la source) et garantit
# qu'aucune ligne ne reste inexpliquée.
# Écrit data/export/copilot_coverage.{csv,json}
python3.12 -m tools.compare_copilot_coverage data/seeds/reference_copilot_2026.xlsx

# Comparaison à une liste de fermetures attendues. Classe chaque ligne en
# present_closure, missing_date, present_vigilance, plan_not_exploded,
# bad_commune_normalization, present_malformed ou absent.
python3.12 -m tools.compare_expected_closures reference.xlsx data/export/data.json

# Crawl du localisateur officiel Société Générale (alimente le cache
# data/cache/sg_crawl.json lu par le collecteur sg_locator).
python3.12 tools/locator_crawl_sg.py
```

`compare_expected_closures` reconnaît les en-têtes français de l'Excel
(`Banque`, `Agence / localisation`, `Commune`, `Date de fermeture`,
`Lien source`, `Score de confiance`) et tolère les dates en texte, du type
« Semaine précédant le 23/06/2026 ».

## Les garde-fous

Trois mécanismes protègent la qualité de la carte. Ils reviennent partout dans
le code, mieux vaut les connaître avant de lire quoi que ce soit :

| Mécanisme | Fichier | Rôle |
|---|---|---|
| **Préfiltre** | `prefilter.py` | Score local un article avant tout appel IA. Un score très bas évite l'appel — mais l'article part en vigilance, il n'est pas perdu. |
| **Cache d'extraction** | `extraction_cache.py` | Ne relance jamais l'IA sur un contenu déjà extrait, pour un triplet `(hash, version, modèle)` donné. |
| **Garde d'extraction** | `extraction_guard.py` | Refuse de publier sur la carte une fermeture dont la localisation ou les preuves sont insuffisantes. |

## Les décisions structurantes

**Pourquoi SQLite et pas une vraie base ?** Le volume est faible (quelques
milliers de lignes), il n'y a qu'un seul écrivain, et un fichier se met en
cache trivialement entre deux runs GitHub Actions. Une base hébergée ajouterait
un coût et un point de panne pour aucun bénéfice.

**Pourquoi un JSON versionné plutôt qu'une API ?** Le site est en lecture seule
et se met à jour une fois par jour. Un fichier statique dans Git donne
l'hébergement gratuit, l'historique des données, et zéro infrastructure. Le
prix à payer : le dépôt Git grossit à chaque run (~65 commits de données à ce
jour), et `data.json` fait déjà 2,8 Mo.

**Pourquoi une IA pour extraire ?** Les formulations de la presse locale sont
trop variées pour des expressions régulières (« ferme ses portes »,
« n'accueillera plus de public », « devient une agence postale »). Le
préfiltre et le cache existent précisément pour que cette IA coûte le moins
cher possible.

**Pourquoi tout est en français dans le code ?** Le domaine est français
(communes, départements, enseignes, presse). Les noms de colonnes et de
variables suivent le vocabulaire métier. Quelques modules récents sont en
anglais — l'incohérence est connue et assumée pour l'instant.
