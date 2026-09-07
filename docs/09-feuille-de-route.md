# 09 — Feuille de route et état d'avancement

> **À lire avant d'entreprendre quoi que ce soit de structurant.** Ce document
> contient une règle de séquençage qui n'est déductible ni du code, ni de
> l'historique Git.

*Dernière mise à jour : 7 septembre 2026.*

## L'objectif

Construire une **base de preuve nationale hiérarchisée** des fermetures et
regroupements d'agences bancaires en France — pas seulement une carte.

Le niveau d'exigence est explicite : les inventaires produits par les
assistants généralistes (Copilot, ChatGPT, Claude) sont le **minimum à
battre**, pas la cible.

## Les trois principes directeurs

1. **La carte reste stricte.** Aucune publication automatique d'un résultat
   faible. Mieux vaut une carte incomplète qu'une carte fausse.
2. **Aucune information ne disparaît faute d'adresse.** Elle descend au niveau
   qui lui correspond : carte → commune non géocodée → signal départemental →
   vigilance. Voir [05-modele-de-donnees.md](05-modele-de-donnees.md).
3. **Chaque ligne du fichier de référence doit être expliquée.** Pas de
   « absent sans raison » : le benchmark de couverture doit classer chaque cas.

## Les cinq cycles

Chaque cycle suit le même rythme : spec → plan → implémentation en TDD. Les
documents correspondants sont dans [`superpowers/`](superpowers/README.md).

### Cycle 1 — Benchmark de couverture · **FAIT** (juin 2026)

Comparateur en lecture seule face au fichier de référence.
`tools/compare_copilot_coverage.py` + `tools/copilot_overrides.json`.

Résultat : 76 lignes traitées, **0 inexpliquée**, 20 présentes sur la carte,
56 en `needs_research`.

### Cycle 2 — Fulltext, préfiltrage, extraction maîtrisée

Découpé en trois sous-cycles. Objectif transversal : récupérer
systématiquement le texte intégral, filtrer localement avant de payer l'IA, et
maîtriser le coût d'extraction.

**2a — FAIT, fusionné dans `main`.**
Tables `articles` et `extractions`. `fulltext.fetch_article()` cache-first avec
métadonnées, `fetch_text()` conservé pour compatibilité.
`backend/extraction_cache.py` avec la clé `(content_hash, extraction_version,
model)` : les résultats `none` sont mis en cache, les `error` restent
réessayables via `attempts`/`retry_after`. Câblé dans `run_pipeline`.

**2b — FAIT, fusionné dans `main`.**
`prefilter.analyse()` renvoyant un `PrefilterResult` (score + banques, communes,
départements, dates, adresses, phrases) ; `is_relevant()` conservé.
`context_builder.build_compact_context()` plafonné à 8 000 caractères. Gate
conservateur : `score <= -2` saute l'IA **mais route en vigilance**. La
détection de communes est une heuristique, pas un jeu de données ; l'INSEE
reste résolu après l'IA.

**2c — EN COURS.** ⚠️
Nouveau schéma d'extraction (`article_type`, `closures[]`,
`department_signals`, `vague_signals`, `needs_sonnet`, `confidence`), gestion
des articles-listes, et **escalade vers Sonnet uniquement sur les cas
ambigus**. Branches `cycle2c-extraction-schema` et
`cycle2c-ii-sonnet-escalation`.

Deux points de vigilance sur ce cycle :
- **Incrémenter `EXTRACTION_VERSION`** dès que le prompt ou le schéma change.
- **Ne pas relancer la pipeline complète avant que 2c soit prêt.** On
  profiterait du préfiltre sans bénéficier de l'extraction large attendue —
  donc on paierait deux fois.

### Cycle 3 — Stockage multi-niveaux explicite

Formaliser les quatre niveaux : points de carte précis, fermetures non
géocodées, signaux départementaux, vigilances vagues. Spec rédigée
(`2026-07-01-cycle3-multilevel-storage-design.md`), branche
`cycle3-department-ui`, largement reflété dans le schéma actuel.

### Cycle 4 — Scan national par département

Balayage département par département avec rapport de couverture, en
priorisant ceux déjà signalés. **Non commencé.**

### Cycle 5 — Comparaison finale

Retrouver tout le fiable du fichier de référence **et** produire des cas
supplémentaires que les assistants généralistes n'ont pas. **Non commencé.**

## La règle de séquençage

> **Ne pas commencer le scan national large (Cycle 4) avant que le Cycle 2
> soit solide** — fulltext, cache et extraction article-liste.

La raison est économique et non négociable : un scan national déclenche des
dizaines de milliers d'extractions. Le lancer avant que le cache, le préfiltre
et le schéma d'extraction soient stabilisés revient à payer plein tarif pour
des résultats qu'il faudra jeter au premier changement de prompt — puisque
tout changement de prompt invalide le cache.

## État des branches

Quatre branches portent du travail non fusionné dans `main` :

| Branche | Contenu |
|---|---|
| `cycle1-copilot-coverage` | Travail résiduel du Cycle 1 |
| `cycle2b-prefilter-scoring` | Travail résiduel du Cycle 2b |
| `docs/update-sources-page` | Mise à jour de la page Sources |
| `fix/ambiguous-commune-geocoding` | Géocodage des communes homonymes |

Les autres branches de cycle ont été fusionnées et supprimées.

## Contraintes techniques à connaître

- **`python3.12` obligatoire.** `config.py` exige 3.10+ ; le `python3` système
  de macOS (3.9) échoue.
- **Pas de PyYAML.** Toute la configuration de données est en JSON ou CSV.
  N'introduisez pas de dépendance YAML.
