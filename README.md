# Veille presse — Fermetures d'agences bancaires

Pipeline Python qui collecte la presse locale + sources officielles, extrait
par IA les fermetures/fusions d'agences bancaires par département, et alimente
une carte web interactive.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Lancer le pipeline

```bash
python run.py
```

Produit `data/export/data.json` et `data/export/departements.geojson`.

La fenêtre par défaut est **18 mois glissants** (rétrospectif + prévisionnel), élargissable
via `--lookback-months` ou `--since`. La date de fin est toujours aujourd'hui.

```bash
python run.py --lookback-months 24
python run.py --lookback-months 30
python run.py --since 2025-01-01
```

La date de départ élargit les fenêtres des collecteurs compatibles
(`Google News`, `GDELT`) et filtre les articles antérieurs avant extraction.

## Voir la carte

```bash
python -m http.server 8000
```

Puis ouvrir http://localhost:8000/frontend/index.html

Pour utiliser depuis l'interface le bouton de relance du pipeline, lancer plutôt :

```bash
python app_server.py 8010
```

Puis ouvrir http://127.0.0.1:8010/frontend/index.html

La carte utilise MapLibre GL JS pour afficher une visualisation par département
(choroplèthe vectorielle) avec filtres interactifs : banque, type de changement
(fermeture/fusion), statut (confirmé/projet/rumeur) et fiabilité des sources.

## Hébergement gratuit

Le mode recommandé est **Vercel Hobby + GitHub Actions** :

- Vercel sert le frontend statique et les exports publics (`frontend/`,
  `data/export/data.json`, `data/export/departements.geojson`).
- GitHub Actions exécute `run.py`, met à jour `data/export/`, commit les exports
  publics, puis Vercel redéploie automatiquement.
- La base SQLite (`data/press.db`) et le cache (`data/cache/`) restent hors Git ;
  le workflow les conserve avec le cache GitHub Actions.

Déploiement Vercel :

1. Connecter le dépôt GitHub dans Vercel.
2. Garder le build command vide ou désactivé : le projet est statique côté Vercel.
3. Garder le output directory à la racine du dépôt. `vercel.json` redirige `/`
   vers `frontend/index.html`.

Secrets GitHub Actions à créer dans `Settings > Secrets and variables > Actions` :

- `ANTHROPIC_API_KEY` obligatoire.
- `OPENAI_API_KEY` optionnel pour le fallback.
- `LEGIFRANCE_CLIENT_ID` et `LEGIFRANCE_CLIENT_SECRET` optionnels.

Variables GitHub Actions optionnelles :

- `ANTHROPIC_MODEL` (défaut `claude-haiku-4-5`) pour l'extraction de volume.
- `ANTHROPIC_FALLBACK_MODEL` (défaut `claude-sonnet-4-6`) pour les articles
  que le modèle primaire ne transforme pas en fermeture exploitable.
- `ANTHROPIC_FALLBACK_ENABLED=0` pour désactiver ce fallback Sonnet.
- `OPENAI_BUDGET_EUR` (défaut `1.0`).
- `GOOGLE_NEWS_WHEN` (défaut `720d`, soit environ 24 mois pour le workflow hébergé).
- `GDELT_THROTTLE_SECONDS` (défaut `12`).

Le workflow `.github/workflows/update-data.yml` se lance tous les jours à
03:17 UTC avec une fenêtre par défaut de 24 mois. Il peut aussi être lancé
manuellement avec une date `since` ou une fenêtre `lookback_months`.

## Sources & limites

- **Périmètre enseignes** : toutes les grandes banques de réseau (liste complète dans
  `config.ENSEIGNES`) — Crédit Agricole, BNP, Société Générale, Banque Populaire,
  Caisse d'Épargne, Crédit Mutuel, CIC, LCL, Crédit du Nord, HSBC, CCF, La Banque
  Postale, Crédit Coopératif.
- **Fenêtre temporelle** : par défaut 18 mois glissants couvrant le rétrospectif
  (depuis ~6 mois) et le prévisionnel (~12 mois à venir). Les fermetures déjà
  effectives depuis le plancher (`since`) sont conservées et affichées (avec
  `statut_temporel == "deja_fermee"`). Une fermeture sans date/période
  exploitable est signalée en vigilance plutôt qu'en fermeture confirmée.
- **Localisateur Société Générale** — ✅ la seule enseigne dont le localisateur
  public affiche un message d'avance (« à compter du… transfère ses activités »).
  6 fermetures nominatives vérifiées sont fournies en seed (`sg_locator.SEED`),
  géocodées à l'adresse précise. Crawl complet : `tools/locator_crawl_sg.py`
  (navigateur headless requis — fiches rendues en JS ; à lancer sur ta machine ;
  sortie ingérée automatiquement par `run.py`).
  ⚠️ **Les autres réseaux n'exposent PAS** d'annonce de fermeture sur leur
  localisateur (vérifié) → pour eux, la presse est la source.
- **Google News** (presse) — source principale des fermetures, **par enseigne**
  (couvre toutes les banques du périmètre). Les requêtes incluent aussi les
  principales marques régionales et anciennes dénominations (`MARQUES_REGIONALES`)
  afin d'améliorer le rappel dans la presse locale.
- **Flux RSS locaux directs** — Actu.fr, Ouest-France, Ici et La Dépêche. Ces
  flux publics complètent Google News sur les dernières publications et sont
  configurables dans `config.LOCAL_RSS_FEEDS`.
- **GDELT** — agrégateur ; rate-limité à 1 requête / 5 s (le collecteur respecte
  la limite et applique un backoff). Best-effort.
- **Légifrance / PISTE** — collecteur d'accords et décisions pouvant mentionner
  des PSE, restructurations ou suppressions d'agences. Il nécessite
  `LEGIFRANCE_CLIENT_ID` et `LEGIFRANCE_CLIENT_SECRET`; sans ces variables, le
  collecteur logue un message et retourne `[]`.
- **Référentiel OSM / Overpass** — fond libre des agences existantes
  (`amenity=bank`, `office=financial`) utilisé comme dénominateur par département
  (`total_agences` dans `data.json`). Il ne crée aucune fermeture future.
- **SIRENE / Recherche d'entreprises** — contrôle a posteriori sans clé API.
  Le statut administratif est exporté dans `controle_sirene` quand il a été
  vérifié. Cette source ne déclenche jamais une publication de fermeture.
- **REGAFI / ACPR** — ⚠️ **au niveau de l'établissement agréé uniquement** (entité
  + siège social), **pas au niveau des agences** : ni adresse d'agence, ni date de
  fermeture d'agence. REGAFI **ne fournit donc pas** « les agences qui ferment ».
  Le collecteur `official.py` reste un ingesteur générique de CSV
  (`data/cache/regafi.csv`, colonnes denomination, commune, code_postal, statut)
  pour toute liste d'agences au bon niveau que tu obtiendrais par ailleurs.
- **Presse professionnelle payante** (Factiva, LexisNexis, Tagaday) — scaffold
  uniquement. Sans `FACTIVA_API_KEY`, `LEXISNEXIS_API_KEY` ou `TAGADAY_API_KEY`,
  le collecteur retourne `[]`; aucun appel réel n'est implémenté.
- **PQR directe** (Ouest-France, etc.) — payante / anti-scraping, non automatisable.

Les sources de contrôle (OSM/Overpass, SIRENE, INSEE/BPE si ajoutée plus tard)
servent au dénombrement ou à la validation, jamais à anticiper une fermeture.

## Recherche web secondaire (providers optionnels)

La revue arborescente des vigilances (`backend/vigilance_review.py`) peut
interroger des providers de recherche web. **Tous sont optionnels et best-effort** :
le pipeline reste pleinement fonctionnel si aucun n'est configuré.

Par défaut, toute la file qualifiée est revue en mode économique
(`VIGILANCE_REVIEW_MAX_PER_RUN=1000`, `VIGILANCE_REVIEW_AI_ENABLED=0`) : le
pipeline exploite les titres, URLs, sources et le géocodage pour publier
uniquement les cas mono-commune très explicites. Pour une campagne exhaustive
avec Anthropic, activer ponctuellement `VIGILANCE_REVIEW_AI_ENABLED=1` ; Haiku
reste le modèle principal et Sonnet le fallback.

- **Brave Search** — activé uniquement si `BRAVE_SEARCH_API_KEY` est défini.
  Sans clé → `[]`. ⚠️ L'offre gratuite Brave est limitée/non garantie dans le
  temps ; ne pas en dépendre pour le run quotidien.
- **Bing Web Search** — activé uniquement si `BING_SEARCH_API_KEY` est défini.
  Sans clé → `[]`. ⚠️ **Important** : l'API Bing Web Search v7 classique est en
  voie de retrait et **Bing Grounding (Azure AI Agents)** n'est **pas** la même
  chose — c'est un service de *grounding* facturé, conditionné à l'éligibilité
  Azure, qui ne donne **pas** un accès brut simple aux résultats de recherche et
  n'est **pas** une source gratuite garantie. Ne jamais supposer que Bing est
  disponible gratuitement.
- **`local_sitemap`** — découverte sans clé via les sitemaps/flux RSS de la
  presse régionale. **Désactivé par défaut** (`LOCAL_SITEMAP_ENABLED=0`) car
  coûteux en I/O et non encore optimisé : à n'activer que pour des campagnes
  ciblées. Sécurisé par un timeout court (`LOCAL_SITEMAP_TIMEOUT`, défaut 5 s),
  un cache par domaine/path entre appels, et un plafond de domaines interrogés
  par requête (`LOCAL_SITEMAP_MAX_DOMAINS`, défaut 2).

Sélection des providers via `WEB_SEARCH_PROVIDERS` (défaut
`brave,bing,local_sitemap` ; `local_sitemap` reste inerte tant que
`LOCAL_SITEMAP_ENABLED=0`).

## Mode « seed URLs » (ingestion directe)

Pour reproduire la couverture d'une base externe sans dépendre d'un moteur de
recherche, on peut ingérer directement une liste d'URLs curées :

```bash
# Liste .txt (une URL par ligne), .csv (colonne « Lien source »/« url ») ou .xlsx
python run.py --seed-urls chemin/vers/urls.csv

# Réutilise l'Excel de référence comme source d'URLs ET comme base de comparaison
python run.py --seed-excel "agences_bancaires_fermetures_2026_pqr_mairies_complete.xlsx"
```

Chaque URL devient un article `{titre, texte, url, date, source}`, passe par
`fulltext.fetch_text` → extraction IA → géocodage (avec repli lieu-dit, ex.
Coëtquidan → Guer) → normalisation de la commune administrative → validation →
upsert closure/source. Le préfiltre n'est pas appliqué (URLs explicitement
fournies). `--seed-excel` affiche en fin de run la comparaison avec la référence.

## Diagnostic de couverture

```bash
python -m tools.compare_expected_closures reference.xlsx data/export/data.json
```

Classe chaque ligne attendue : `present_closure`, `missing_date`,
`present_vigilance`, `plan_not_exploded`, `bad_commune_normalization`,
`present_malformed`, `absent`. Reconnaît les en-têtes français de l'Excel
(`Banque`, `Agence / localisation`, `Commune`, `Date de fermeture`,
`Lien source`, `Score de confiance`…) et tolère les dates en texte
(« Semaine précédant le 23/06/2026 »).

## Tests

```bash
python -m pytest -v
```

## Configuration

Tout se règle dans `config.py` : enseignes suivies, mots-clés, départements,
et les modèles IA. Par défaut, `ANTHROPIC_MODEL=claude-haiku-4-5` traite le
volume et `ANTHROPIC_FALLBACK_MODEL=claude-sonnet-4-6` sert de filet pour les
articles que Haiku ne transforme pas en fermeture exploitable.

Variables d'environnement optionnelles :

- `ANTHROPIC_MAX_RETRIES`, `ANTHROPIC_RETRY_BASE_SECONDS`,
  `ANTHROPIC_RETRY_MAX_SECONDS` pilotent les retries sur erreurs transitoires
  Anthropic (`429`, `500`, `504`, `529`).
- `ANTHROPIC_FALLBACK_ENABLED=0` désactive le fallback Sonnet.
- `OPENAI_API_KEY` active un fallback OpenAI quand Anthropic échoue encore sur
  une erreur transitoire après retries.
- `OPENAI_BUDGET_EUR` plafonne l'estimation de coût OpenAI (défaut : `1.0`).
  Le suivi est stocké dans `data/cache/openai_budget.json`.
- `OPENAI_FALLBACK_MODEL` vaut `gpt-5.4-nano` par défaut ; les prix estimés
  suivent les tarifs standard publics du modèle (`OPENAI_INPUT_EUR_PER_M`,
  `OPENAI_OUTPUT_EUR_PER_M` permettent de surcharger ces valeurs).
- `LEGIFRANCE_CLIENT_ID` / `LEGIFRANCE_CLIENT_SECRET` pour activer Légifrance via PISTE.
- `LEGIFRANCE_ENV=sandbox` pour utiliser les URLs sandbox PISTE ; par défaut,
  le collecteur utilise la production (`oauth.piste.gouv.fr` / `api.piste.gouv.fr`).
- `LEGIFRANCE_SCOPE` vaut `openid searchUsingPOST` par défaut, car le collecteur
  utilise l'endpoint de recherche Légifrance.
- `LEGIFRANCE_MAX_QUERIES` plafonne le nombre de recherches par run (défaut : 8).
- `LEGIFRANCE_THROTTLE_SECONDS` temporise les appels Légifrance (défaut : 2 s).
  Les quotas PISTE fournis indiquent notamment `2` messages/seconde pour
  `searchUsingPOST`; `0.6` seconde entre deux requêtes reste volontairement
  sous cette limite.
- `FACTIVA_API_KEY`, `LEXISNEXIS_API_KEY`, `TAGADAY_API_KEY` réservées au scaffold
  presse pro, sans appel réel à ce stade.
