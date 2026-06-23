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

## Voir la carte

```bash
python -m http.server 8000
```

Puis ouvrir http://localhost:8000/frontend/index.html

La carte utilise MapLibre GL JS pour afficher une visualisation par département
(choroplèthe vectorielle) avec filtres interactifs : banque, type de changement
(fermeture/fusion), statut (confirmé/projet/rumeur) et fiabilité des sources.

## Sources & limites

- **Google News** (presse) — source principale des fermetures d'agences.
- **GDELT** — agrégateur ; rate-limité à 1 requête / 5 s (le collecteur respecte
  la limite et applique un backoff). Best-effort.
- **REGAFI / ACPR** — ⚠️ **au niveau de l'établissement agréé uniquement** (entité
  + siège social), **pas au niveau des agences** : ni adresse d'agence, ni date de
  fermeture d'agence. REGAFI **ne fournit donc pas** « les agences qui ferment ».
  Le collecteur `official.py` reste un ingesteur générique de CSV
  (`data/cache/regafi.csv`, colonnes denomination, commune, code_postal, statut)
  pour toute liste d'agences au bon niveau que tu obtiendrais par ailleurs.
- **PQR directe** (Ouest-France, etc.) — payante / anti-scraping, non automatisable.

## Tests

```bash
python -m pytest -v
```

## Configuration

Tout se règle dans `config.py` : enseignes suivies, mots-clés, départements,
et le modèle IA (`ANTHROPIC_MODEL`, par défaut `claude-opus-4-8` ;
`claude-haiku-4-5` pour réduire le coût en volume).
