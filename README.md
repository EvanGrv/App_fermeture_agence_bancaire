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

## Source officielle (optionnelle)

Déposer un export REGAFI dans `data/cache/regafi.csv`
(colonnes : denomination, commune, code_postal, statut).

## Tests

```bash
python -m pytest -v
```

## Configuration

Tout se règle dans `config.py` : enseignes suivies, mots-clés, départements,
et le modèle IA (`ANTHROPIC_MODEL`, par défaut `claude-opus-4-8` ;
`claude-haiku-4-5` pour réduire le coût en volume).
