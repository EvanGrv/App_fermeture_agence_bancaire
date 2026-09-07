# 08 — Configuration

## Comment ça marche

Tout se règle par variables d'environnement. [`config.py`](../config.py) les
lit au chargement, applique un défaut, et expose des constantes. Le reste du
code lit ces constantes, jamais `os.getenv` — à quelques exceptions près dans
les collecteurs.

En local, `backend/env.py` charge le fichier `.env` de la racine. En CI, les
valeurs viennent des *secrets* et *variables* du dépôt.

**Toutes les variables ont un défaut fonctionnel, sauf les clés d'API.** Un
`.env` contenant la seule clé du fournisseur d'extraction suffit à faire
tourner le projet.

Conventions : un interrupteur vaut `0` pour désactiver et n'importe quoi
d'autre pour activer — sauf `VIGILANCE_REVIEW_AI_ENABLED` et
`INCLUDE_CREDIT_MUNICIPAL`, qui exigent exactement `1`.

## Extraction IA

| Variable | Défaut | Rôle |
|---|---|---|
| `EXTRACTION_PROVIDER` | `openai` | `openai` ou `anthropic` |
| `OPENAI_API_KEY` | — | Requise en mode openai |
| `OPENAI_MODEL` | `gpt-5.4-nano` | |
| `OPENAI_BUDGET_EUR` | `1.0` | Plafond de dépense par run |
| `ANTHROPIC_API_KEY` | — | Requise en mode anthropic |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5` | Traite le volume |
| `ANTHROPIC_FALLBACK_MODEL` | `claude-sonnet-4-6` | Filet pour les articles ambigus |
| `ANTHROPIC_FALLBACK_ENABLED` | `1` | |
| `STRUCTURED_SONNET_ESCALATION_ENABLED` | `1` | Escalade vers Sonnet |
| `STRUCTURED_SONNET_MIN_CONFIDENCE` | `0.65` | En dessous, on escalade |

### Cache d'extraction

| Variable | Défaut | Rôle |
|---|---|---|
| `EXTRACTION_VERSION` | `5` | **Clé du cache.** À incrémenter dès que le prompt ou le schéma change |
| `EXTRACTION_MAX_ATTEMPTS` | `3` | Tentatives avant abandon |
| `EXTRACTION_RETRY_BASE_MIN` | `60` | Base du backoff, en minutes |

> Le cache est indexé par `(content_hash, extraction_version, model)`. Modifier
> le prompt **sans** incrémenter `EXTRACTION_VERSION` fait servir d'anciens
> résultats produits par un autre prompt. C'est le piège le plus coûteux du
> projet, et il est silencieux.

## Fenêtre temporelle

| Variable | Défaut | Rôle |
|---|---|---|
| `LOOKBACK_MONTHS_DEFAULT` | `18` | Fenêtre sans argument CLI |
| `GOOGLE_NEWS_WHEN` | `180d` | Opérateur `when:`. **`m` = minutes, pas mois** |
| `GDELT_TIMESPAN` | — | Fenêtre GDELT |
| `GDELT_THROTTLE_SECONDS` | `12` en CI | Imposé par le service |

## Préfiltre

| Variable | Défaut | Rôle |
|---|---|---|
| `PREFILTER_MIN_SCORE` | `-2` | Seuil de saut de l'IA. Conservateur par conception : l'augmenter réduit le coût et le rappel |
| `PREFILTER_CONTEXT_MAX_CHARS` | `8000` | Taille du contexte envoyé au modèle |

## Périmètre métier

| Variable | Défaut | Rôle |
|---|---|---|
| `INCLUDE_CREDIT_MUNICIPAL` | `0` | Ajoute le Crédit Municipal aux enseignes suivies (exiger `1`) |

Les listes `ENSEIGNES`, `MARQUES_REGIONALES`, `TERMES_FERMETURE`,
`POSTAL_POINT_TERMS`, `POSTAL_BANKING_TERMS`, `RH_TERMS`, `LOCAL_RSS_FEEDS` et
`DEPARTEMENTS` sont **en dur dans `config.py`**, pas configurables par
environnement. C'est là qu'on ajoute une enseigne ou une formulation de
fermeture.

## Revue des vigilances

| Variable | Défaut local | Défaut CI | Rôle |
|---|---|---|---|
| `VIGILANCE_REVIEW_ENABLED` | `1` | `1` | Active la revue |
| `VIGILANCE_REVIEW_MIN_SCORE` | `3` | — | Score minimal pour être revu |
| `VIGILANCE_REVIEW_MAX_PER_RUN` | `6` | `6` | Plafond de la file |
| `VIGILANCE_REVIEW_MAX_QUERIES_PER_ITEM` | `3` | `3` | Requêtes par vigilance |
| `VIGILANCE_REVIEW_AI_ENABLED` | **`0`** | **`1`** | Poste de coût IA distinct (exiger `1`) |
| `VIGILANCE_REVIEW_COOLDOWN_DAYS` | `7` | — | Délai avant de re-réviser |

## Plans multi-agences

| Variable | Défaut | Rôle |
|---|---|---|
| `PLAN_EXPLOSION_ENABLED` | `1` | |
| `PLAN_EXPLOSION_MAX_COMMUNES` | `30` | Garde-fou contre l'explosion combinatoire |

## Recherche web

| Variable | Défaut | Rôle |
|---|---|---|
| `WEB_SEARCH_PROVIDERS` | `brave,local_sitemap` | Liste ordonnée |
| `BRAVE_SEARCH_API_KEY` | — | |
| `BING_SEARCH_API_KEY` | — | |
| `WEB_SEARCH_API_KEY` | — | Clé générique héritée |
| `LOCAL_SITEMAP_ENABLED` | `0` local / `0` CI | Coûteux en requêtes HTTP |
| `LOCAL_SITEMAP_TIMEOUT` | `5` | Secondes |
| `LOCAL_SITEMAP_MAX_DOMAINS` | `2` | Domaines par requête |
| `LOCAL_SITEMAP_MAX_URLS_PER_DOMAIN` | — | |
| `LOCAL_SITEMAP_DOMAINS` | 14 domaines de PQR | Liste séparée par virgules |

## Canal La Banque Postale

| Variable | Défaut | Rôle |
|---|---|---|
| `LAPOSTE_OPEN_DATA_ENABLED` | `1` | Synchronisation du réseau officiel |
| `LAPOSTE_POINTS_DATASET_ID` | `laposte-poincont2` | ~20 000 points de contact |
| `LAPOSTE_CALENDAR_DATASET_ID` | `tjwztt6h44ve52i7fln6rbxz` | Calendrier bancaire |
| `LAPOSTE_DATA_API_BASE` | `https://data.laposte.fr/...` | |
| `LAPOSTE_MISSING_CONFIRMATIONS` | `2` | Disparitions consécutives avant de conclure |
| `LAPOSTE_CALENDAR_MAX_CHECKS` | `20` | |
| `LBP_AGENCES_CSV_URL` | vide | Sinon lecture de `data/cache/lbp_agences.csv` |
| `POSTAL_WEB_ENABLED` | `1` | Recherche web dédiée |
| `POSTAL_WEB_MAX_QUERIES` | `8` | |
| `POSTAL_HISTORY_ENABLED` | `1` | Backfill |
| `POSTAL_HISTORY_MIN_DAYS` | `700` | **En dessous, le collecteur ne s'exécute pas** |
| `POSTAL_HISTORY_WEB_MAX_QUERIES` | `12` | |

## Agrégateurs de presse

| Variable | Défaut |
|---|---|
| `MEDIACLOUD_ENABLED` / `_API_KEY` | `1` / — |
| `MEDIACLOUD_MAX_PAGES` / `_MAX_ARTICLES` | `2` / `200` |
| `MEDIACLOUD_COLLECTION_IDS` | `34412146,38379799` |
| `EVENT_REGISTRY_ENABLED` / `_API_KEY` | `1` / — |
| `EVENT_REGISTRY_MAX_PAGES` / `_MAX_ARTICLES` | `1` / `100` |
| `EVENT_REGISTRY_SOURCE_LOCATION_URI` | page Wikipédia France |

## Common Crawl

| Variable | Défaut | Rôle |
|---|---|---|
| `COMMON_CRAWL_ENABLED` | `1` | |
| `COMMON_CRAWL_MIN_DAYS` | `700` | **En dessous, ne s'exécute pas** |
| `COMMON_CRAWL_MAX_DOMAINS` | `4` | |
| `COMMON_CRAWL_MAX_INDEXES` | `4` | |
| `COMMON_CRAWL_RECORDS_PER_DOMAIN` | `12` | |
| `COMMON_CRAWL_MAX_ARTICLES` | `40` | |
| `COMMON_CRAWL_TIMEOUT` | `20` | Secondes |
| `COMMON_CRAWL_MAX_RECORD_BYTES` | `2 Mo` | |
| `COMMON_CRAWL_THROTTLE_SECONDS` | `2` | |
| `COMMON_CRAWL_RETRIES` | `1` | |
| `COMMON_CRAWL_RETRY_BASE_SECONDS` | `5` | |
| `COMMON_CRAWL_MAX_CONSECUTIVE_ERRORS` | `4` | Coupe-circuit |
| `COMMON_CRAWL_DOMAINS` | 18 domaines de presse | |

## Légifrance

| Variable | Défaut |
|---|---|
| `LEGIFRANCE_CLIENT_ID` / `_CLIENT_SECRET` | — |
| `LEGIFRANCE_ENV` / `_SCOPE` | — |

## Chemins

Dérivés de la racine du dépôt dans `config.py`, non configurables :
`DATA_DIR`, `EXPORT_DIR`, `CACHE_DIR`, `DB_PATH` (`data/press.db`),
`DATA_JSON` (`data/export/data.json`), `GEOJSON_PATH`.

## Ajouter une variable

1. La lire dans `config.py` avec un défaut sûr, et un commentaire expliquant
   **pourquoi** ce défaut.
2. L'ajouter au bloc `env:` de `.github/workflows/update-data.yml`, en
   `${{ vars.X || 'défaut' }}` pour un réglage, `${{ secrets.X }}` pour un
   secret.
3. L'ajouter au tableau correspondant de ce document.
4. Si elle change un comportement, couvrir les deux branches dans les tests.
