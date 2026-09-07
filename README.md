# Veille presse — Fermetures d'agences bancaires

Base de preuve nationale des fermetures et regroupements d'agences bancaires
en France, constituée automatiquement à partir de la presse locale et de
sources officielles, et publiée sous forme de carte et de tableaux.

Ce n'est pas seulement une carte : c'est une base **hiérarchisée**, où chaque
information est rangée au niveau de certitude qu'elle mérite. Une fermeture
nominative et datée finit sur la carte ; une rumeur syndicale finit en
vigilance. Les deux sont conservées.

**→ [La documentation complète est dans `docs/`](docs/README.md)**

## Démarrage rapide

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Renseigner au minimum la clé du fournisseur d'extraction
echo "OPENAI_API_KEY=sk-..." > .env

# Un run court, pour vérifier que tout fonctionne
python3.12 run.py --lookback-days 7

# Voir le résultat
python3.12 -m http.server 8000     # puis http://localhost:8000/frontend/
```

> **`python3.12` est requis.** Le `python3` du système macOS est un 3.9 et
> échouera.

## Comment ça marche

```
sources de presse  ──▶  run.py / backend/pipeline.py  ──▶  data/export/data.json
et sources officielles      (préfiltre → IA → validation)         │
                                        │                         ▼
                                data/press.db                 frontend/
                             (SQLite, local)                (statique, Vercel)
```

Un batch quotidien collecte des articles, les filtre localement, en extrait
des fermetures structurées par IA, les valide, les géocode, et écrit un JSON.
Le frontend est un site statique qui lit ce JSON. Il n'y a **pas de serveur en
production**.

## Où trouver quoi

| Vous voulez… | Allez voir |
|---|---|
| Lancer le projet en local | [docs/01-demarrage.md](docs/01-demarrage.md) |
| Comprendre l'ensemble en 5 minutes | [docs/02-architecture.md](docs/02-architecture.md) |
| Modifier le traitement des articles | [docs/03-pipeline.md](docs/03-pipeline.md) |
| Ajouter ou déboguer une source | [docs/04-sources.md](docs/04-sources.md) |
| Comprendre le stockage et l'export | [docs/05-modele-de-donnees.md](docs/05-modele-de-donnees.md) |
| Travailler sur la carte | [docs/06-frontend.md](docs/06-frontend.md) |
| Diagnostiquer un run échoué | [docs/07-exploitation.md](docs/07-exploitation.md) |
| Savoir à quoi sert une variable | [docs/08-configuration.md](docs/08-configuration.md) |
| **Savoir quoi faire ensuite** | [docs/09-feuille-de-route.md](docs/09-feuille-de-route.md) |
| Décoder un terme du code | [docs/10-glossaire.md](docs/10-glossaire.md) |

## Structure

```
run.py              orchestrateur, point d'entrée unique
config.py           toute la configuration et le périmètre métier
app_server.py       serveur de développement (non déployé)
backend/            pipeline, collecteurs, extraction, stockage, export
frontend/           site statique : index.html, app.js, style.css
tools/              outils de diagnostic en lecture seule
tests/              53 fichiers, sans accès réseau
data/export/        les données publiées (versionnées)
docs/               la documentation
```

## Tests

```bash
python3.12 -m pytest -q
```

La suite doit passer avant tout commit — c'est aussi une étape bloquante du
workflow GitHub Actions, exécutée avant toute écriture de données.

## Les trois règles à connaître

1. **La carte reste stricte.** Aucune publication automatique d'un résultat
   faible.
2. **Aucune information ne disparaît.** Ce qui ne peut pas être publié descend
   d'un niveau au lieu d'être jeté.
3. **`EXTRACTION_VERSION` doit être incrémentée** dès que le prompt ou le
   schéma d'extraction change, sinon le cache sert d'anciens résultats — en
   silence.
