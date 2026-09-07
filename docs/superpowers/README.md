# Historique de conception

Ce dossier conserve les documents de conception rédigés cycle par cycle, selon
le rythme **spec → plan → implémentation en TDD**.

## Comment lire ces documents

Ce sont des **archives datées, pas de la documentation courante.** Ils
décrivent ce qui était prévu au moment où ils ont été écrits. Là où ils
divergent du code, **c'est le code qui fait foi** — et pour l'état actuel du
projet, ce sont les fichiers [01 à 10](../README.md) qui font référence.

Leur valeur est ailleurs : ils expliquent **pourquoi** les décisions ont été
prises. Avant de « simplifier » un mécanisme qui paraît alambiqué — le cache
d'extraction, le gate conservateur du préfiltre, la hiérarchie à quatre niveaux
— cherchez la spec correspondante. La contrainte qui l'a motivé est
généralement toujours là.

Les deux dossiers se répondent : une **spec** décrit l'architecture retenue et
ses arbitrages ; un **plan** en découpe la mise en œuvre en tâches testables.

## Index

Statuts au 7 septembre 2026. Le détail des cycles est dans
[09-feuille-de-route.md](../09-feuille-de-route.md).

| Date | Sujet | Cycle | Spec | Plan | Statut |
|---|---|---|---|---|---|
| 2026-06-23 | Veille presse locale — conception initiale | fondations | [spec](specs/2026-06-23-presse-locale-fermetures-bancaires-design.md) | [plan](plans/2026-06-23-presse-locale-fermetures-bancaires.md) | Livré |
| 2026-06-25 | Rétrospective et couverture | fondations | — | [plan](plans/2026-06-25-veille-fermetures-retrospective-et-couverture.md) | Livré |
| 2026-06-29 | Benchmark de couverture | **1** | [spec](specs/2026-06-29-copilot-coverage-benchmark-design.md) | [plan](plans/2026-06-29-copilot-coverage-benchmark.md) | Livré |
| 2026-06-30 | Fulltext systématique et cache | **2a** | [spec](specs/2026-06-30-cycle2a-fulltext-cache-design.md) | [plan](plans/2026-06-30-cycle2a-fulltext-cache.md) | Livré, fusionné |
| 2026-07-01 | Préfiltrage et scoring | **2b** | [spec](specs/2026-07-01-cycle2b-prefilter-scoring-design.md) | [plan](plans/2026-07-01-cycle2b-prefilter-scoring.md) | Livré, fusionné |
| 2026-07-01 | Schéma d'extraction | **2c-i** | [spec](specs/2026-07-01-cycle2c-i-extraction-schema-design.md) | [plan](plans/2026-07-01-cycle2c-i-extraction-schema.md) | **En cours** |
| 2026-07-01 | Escalade Sonnet | **2c-ii** | [spec](specs/2026-07-01-cycle2c-ii-sonnet-escalation-design.md) | — | **En cours** |
| 2026-07-01 | Stockage multi-niveaux | **3** | [spec](specs/2026-07-01-cycle3-multilevel-storage-design.md) | — | Spec écrite, implémentation partielle |

Les cycles **4** (scan national par département) et **5** (comparaison finale)
n'ont ni spec ni plan à ce jour.

## Ajouter un cycle

1. Écrire la spec dans `specs/AAAA-MM-JJ-<sujet>-design.md` : le problème, les
   approches envisagées, celle retenue et pourquoi, l'architecture, la
   stratégie de test.
2. Écrire le plan dans `plans/AAAA-MM-JJ-<sujet>.md` : des tâches ordonnées et
   testables, chacune avec son test d'abord.
3. Implémenter en TDD, une tâche par commit.
4. **Ajouter la ligne au tableau ci-dessus** et mettre à jour
   [09-feuille-de-route.md](../09-feuille-de-route.md).
