# 03 — La pipeline

Ce document décrit `run_pipeline()` dans
[`backend/pipeline.py`](../backend/pipeline.py), la boucle qui transforme des
articles bruts en enregistrements exploitables.

## Vue d'ensemble

```
  pour chaque collecteur (11 au total)
    │
    ├─ collect()  ──────── erreur ? on log et on passe au suivant
    │
    └─ pour chaque article
         │
         ├─ 1. Filtre temporel      → hors fenêtre ? on jette
         ├─ 2. URL déjà vue ?       → oui ? on saute
         ├─ 3. Préfiltre binaire    → non pertinent ? on marque vu, on jette
         ├─ 4. Récupération fulltext (cache-first)
         ├─ 5. Préfiltre scoré      → score très bas ? → VIGILANCE
         ├─ 6. Raccourci postal     → cas LBP déterministe, sans IA
         ├─ 7. Extraction IA        → via cache
         ├─ 8. Persistance des signaux départementaux et vagues
         ├─ 9. Mapping → fermetures candidates
         └─ 10. Pour chaque candidate :
                 fenêtre temporelle ? garde d'extraction ? géocodage ?
                 ├─ tout est bon     → CARTE
                 └─ un critère manque → NON GÉOCODÉE ou VIGILANCE
```

L'invariant à retenir : **chaque branche qui refuse une publication écrit
ailleurs**. Il n'y a aucun chemin où une information pertinente est simplement
abandonnée.

## Les étapes en détail

### 1. Filtre temporel

`_parse_article_date()` tolère l'ISO 8601 et le format RFC 2822 des flux RSS.
Un article antérieur à `since_date` est compté dans `recap["hors_periode"]` et
ignoré. Un article **sans date** passe : on préfère un faux positif à une perte.

### 2. Déduplication par URL

La table `seen_urls` mémorise toute URL déjà traitée. C'est ce qui rend les
runs quotidiens peu coûteux : seuls les articles nouveaux sont traités.

> **Piège :** une URL est marquée vue même quand l'article est rejeté. Si vous
> corrigez un bug de traitement et voulez retraiter d'anciens articles, il faut
> les retirer de `seen_urls` — c'est exactement ce que fait
> `store.requeue_postal_articles()` pour le canal postal.
>
> Exception délibérée : une extraction en **erreur** ne marque pas l'URL vue,
> pour que le run suivant réessaie.

### 3. Préfiltre binaire

`prefilter.is_relevant()` : l'article mentionne-t-il au moins une enseigne
suivie et au moins un terme de fermeture ? Sinon, on s'arrête là. C'est un
test très bon marché qui élimine l'essentiel du bruit avant tout accès réseau.

### 4. Récupération du texte intégral

`fulltext.fetch_article()` est **cache-first** : il consulte la table
`articles` avant de tenter un téléchargement. Le texte est concaténé au résumé
du flux et tronqué à 20 000 caractères.

Un échec de récupération n'est pas fatal : le `try/except` est volontairement
silencieux, et l'article continue avec le seul résumé du flux.

### 5. Préfiltre scoré

`prefilter.analyse()` renvoie un `PrefilterResult` : un score, plus les
banques, communes, départements, dates et adresses repérés localement, et les
phrases où ils apparaissent.

Le score monte avec les indices de fermeture nominative et descend avec les
marqueurs RH — un article qui parle de « plan social » et de « syndicat » sans
jamais dire « agence » est probablement un article social, pas une fermeture.

Si `score <= PREFILTER_MIN_SCORE` (**-2** par défaut, volontairement très
conservateur), on **saute l'appel IA** — mais l'article est routé en vigilance.
On économise le coût, on ne perd pas l'information.

`context_builder.build_compact_context()` construit ensuite un extrait
plafonné à 8 000 caractères autour des phrases pertinentes. **C'est ce contexte
compact, et non l'article entier, qui part à l'IA.** C'est le principal levier
de coût du projet.

### 6. Raccourci postal déterministe

`_ingest_postal_fallback()` traite sans IA les cas de fermeture de bureau de
poste reconnaissables de façon déterministe. Le canal La Banque Postale a sa
propre logique dans toute la pipeline, parce que la presse parle de « bureau
de poste » là où le métier voit une agence bancaire.

### 7. Extraction IA

`extract_cached_with_status()` interroge la table `extractions` avec la clé
`(content_hash, extraction_version, model)` :

- **hit** → on réutilise le résultat, aucun appel API
- **`none` en cache** → l'IA a déjà répondu « rien ici », on ne redemande pas
- **`error` en cache** → réessayable, avec backoff (`attempts`, `retry_after`)
- **miss** → appel réel au modèle

> **Règle non négociable :** si vous modifiez le prompt ou le schéma
> d'extraction, **incrémentez `EXTRACTION_VERSION`** dans `config.py`. Sinon le
> cache servira d'anciens résultats produits par un prompt différent. C'est le
> piège le plus coûteux du projet.

Le modèle renvoie une structure Pydantic : `article_type`, `closures[]`,
`department_signals[]`, `vague_signals[]`, `needs_sonnet`, `confidence`.

### 8. Persistance des signaux

`_persist_structured_signals()` écrit les signaux départementaux et vagues dans
leurs tables **avant** tout traitement des fermetures. Un article qui dit
« la banque X fermera 15 agences dans la Loire » sans les nommer produit un
`department_signal` exploitable même si aucune fermeture précise n'en sort.

### 9. Mapping

`ingest_map.map_result()` convertit la sortie du modèle en fermetures
candidates au format de la base, et convertit la `confidence` (0.0–1.0) en
`fiabilite` entière (0–5).

### 10. Publication, ou dégradation

Pour chaque fermeture candidate, trois obstacles successifs :

1. **Fenêtre temporelle** — `_retenir_fermeture()`. Échec → `closures_unlocated`
   avec la raison « hors fenêtre temporelle ».
2. **Garde d'extraction** — `extraction_guard.evaluate()`. Échec →
   `closures_unlocated` avec la raison du refus.
3. **Géocodage** — pas de coordonnées → `closures_unlocated`.

Si aucune candidate n'est publiée et qu'aucun signal de vigilance n'a été
produit, l'article lui-même devient une vigilance, avec la liste des raisons de
rejet. **C'est le filet de dernier recours.**

## Le récapitulatif

`run_pipeline()` renvoie un dictionnaire de compteurs, affiché en fin de run :

| Clé | Signification |
|---|---|
| `articles` | articles vus, toutes sources confondues |
| `hors_periode` | rejetés par le filtre temporel |
| `filtres` | ayant passé le préfiltre binaire |
| `extraits` | fermetures candidates entrées en phase de publication |
| `fermetures` | publiées sur la carte |
| `vigilances` | signaux faibles conservés |
| `rejets_validation` | refusés par la validation |

**Comment lire ces chiffres :** un `filtres` élevé avec un `fermetures` très
bas signale soit un préfiltre trop laxiste, soit une garde d'extraction trop
stricte. Un `vigilances` qui explose signale généralement une régression du
géocodage.

## Les étapes hors `run_pipeline`

`run.py` exécute autour de la boucle principale plusieurs traitements qui ne
partent pas d'articles de presse :

| Étape | Ce qu'elle fait |
|---|---|
| Synchronisation La Poste | Compare le référentiel officiel à la version précédente ; une disparition confirmée `LAPOSTE_MISSING_CONFIRMATIONS` fois devient un signal |
| Fermetures SG vérifiées | Injecte les fermetures issues du localisateur officiel Société Générale, géocodées à l'adresse exacte, **sans appel IA** |
| Référentiel d'agences | Charge les agences depuis OpenStreetMap et La Banque Postale (contexte d'affichage, pas des fermetures) |
| Éclatement des plans | Un article « la banque X ferme 15 agences » devient jusqu'à `PLAN_EXPLOSION_MAX_COMMUNES` fermetures individuelles, chacune repassant par la garde d'extraction |
| Revue des vigilances | Chaque vigilance de score suffisant devient le point de départ d'une recherche web ciblée — une vigilance peut ainsi « remonter » en fermeture publiée |
| Contrôles SIRENE | Interroge l'état administratif de chaque fermeture publiée |
| Export | Écrit `data.json`, le CSV, le GeoJSON et les rapports d'audit |
