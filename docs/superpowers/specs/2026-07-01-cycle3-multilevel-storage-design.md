# Cycle 3 — Stockage multi-niveaux (Design initial)

Date : 2026-07-01
Statut : tranche backend implémentée.

## Principe

La carte reste stricte : seuls les points géocodés et publiables restent dans
`closures`. La base devient plus large : une information exploitable ne disparaît
pas faute de lat/lon ou d'adresse.

## Tiers persistés

- `closures` : points précis pour la carte.
- `closures_unlocated` : agence/commune nommée mais non pointable ou non publiable
  immédiatement.
- `department_signals` : signal comptable départemental.
- `vague_signals` : signal régional/national ou trop vague.
- `vigilances` : file de revue et compatibilité avec les anciens écrans/outils.

## Intégration pipeline

Le pipeline 2c lit `ExtractionResult` :

- `closures[]` publiables et géocodées → `closures`.
- `closures[]` non géocodées / hors fenêtre / non publiables → `closures_unlocated`
  + vigilance de revue.
- `department_signals[]` → `department_signals` + vigilance agrégée.
- `vague_signals[]` → `vague_signals` + vigilance agrégée.

## Export

`data.json` expose désormais :

- `closures_unlocated`
- `department_signals`
- `vague_signals`

`department_estimates` additionne :

- `precise_count`
- `unlocated_count`
- `department_signal_count`
- `estimated_count`

La séparation produit reste possible : la vue Carte s'appuie sur `closures`,
la future vue Département pourra s'appuyer sur `department_estimates` et les
tiers non pointés.
