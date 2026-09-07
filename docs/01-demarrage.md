# 01 — Démarrage

## Prérequis

- **Python 3.12.** Le code utilise la syntaxe `str | None` (PEP 604) et exige
  3.10 minimum. Sur macOS, le `python3` du système est souvent un 3.9 et
  **échouera** : utilisez explicitement `python3.12`.
- Aucune base de données à installer : le stockage est un fichier SQLite créé
  automatiquement dans `data/press.db`.
- Aucun outil de build frontend : le front est du HTML/CSS/JS servi tel quel.

## Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration minimale

Créez un fichier `.env` à la racine. Une seule clé est réellement obligatoire
pour un premier run : celle du fournisseur d'extraction IA.

```bash
# Fournisseur d'extraction : "openai" (défaut) ou "anthropic"
EXTRACTION_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

Tout le reste a une valeur par défaut fonctionnelle. Les collecteurs qui
demandent une clé absente se désactivent silencieusement au lieu de faire
échouer le run. La liste complète des variables est dans
[08-configuration.md](08-configuration.md).

> `.env` est dans le `.gitignore` et ne doit jamais être committé.

## Premier run

Le run complet interroge une dizaine de sources et appelle l'IA sur chaque
article retenu : comptez plusieurs dizaines de minutes et un coût API réel.
Pour un premier essai, restreignez fortement la fenêtre :

```bash
python3.12 run.py --lookback-days 7
```

Le script affiche sa progression étape par étape, puis un récapitulatif
chiffré. À la fin, `data/export/data.json` est régénéré.

### Les autres formes d'appel

```bash
# Fenêtre glissante
python3.12 run.py --lookback-days 60
python3.12 run.py --lookback-months 24

# Date de départ exacte
python3.12 run.py --since 2026-01-01

# Ingestion directe d'une liste d'URLs curées (.txt, .csv ou .xlsx)
python3.12 run.py --seed-urls mes_urls.txt

# Idem, mais l'Excel sert à la fois de source d'URLs et de référence de comparaison
python3.12 run.py --seed-excel data/seeds/reference_copilot_2026.xlsx
```

Sans argument, la fenêtre par défaut est de 18 mois glissants
(`LOOKBACK_MONTHS_DEFAULT`).

## Voir le résultat

Le frontend est statique et lit `data/export/data.json`. Un simple serveur de
fichiers suffit :

```bash
python3.12 -m http.server 8000
# puis ouvrir http://localhost:8000/frontend/
```

Pour disposer en plus du bouton « lancer la pipeline » de l'onglet Paramètres,
utilisez le serveur applicatif, qui ajoute quelques routes `/api/pipeline/*` :

```bash
python3.12 app_server.py
```

## Tests

```bash
python3.12 -m pytest -q
```

53 fichiers de tests, sans accès réseau : les collecteurs sont testés contre
les fixtures de `tests/fixtures/`. La suite doit passer avant tout commit —
c'est aussi une étape bloquante du workflow GitHub Actions.

## Ce qui n'est pas versionné

`data/press.db` (la base de travail) et `data/cache/` (le cache HTTP et
fulltext) sont locaux et reconstructibles. Seul `data/export/` est versionné,
parce que c'est ce que le site déployé consomme. Voir
[07-exploitation.md](07-exploitation.md).
