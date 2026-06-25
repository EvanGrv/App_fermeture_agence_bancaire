"""Module de récupération du texte intégral d'un article web.

API publique :
    fetch_text(url, fetch=None, cache_dir=None) -> str

Comportement :
- Télécharge le HTML via `fetch` (injectable pour les tests).
- Extrait le corps de l'article avec trafilatura.
- Mise en cache disque (hash SHA-256 de l'URL, 16 premiers caractères).
- Best-effort : toute exception → retourne "" sans propager.
- Seuls les résultats non vides sont mis en cache ; les échecs transitoires
  (site indisponible, anti-bot) peuvent ainsi être retentés lors du prochain run.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import requests
import trafilatura

import config

_HEADERS = {
    "User-Agent": "veille-presse/1.0",
}


def _default_fetch(url: str) -> str:
    resp = requests.get(url, timeout=10, headers=_HEADERS)
    resp.raise_for_status()
    return resp.text


def _cache_path(url: str, cache_dir: Path) -> Path:
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    return cache_dir / f"{key}.txt"


def fetch_text(url: str, fetch=None, cache_dir=None) -> str:
    """Retourne le texte principal de l'article à `url`.

    Paramètres
    ----------
    url       : URL de l'article à télécharger.
    fetch     : callable (url) -> str (HTML brut). Par défaut : requests.get.
    cache_dir : répertoire de cache. Par défaut : config.CACHE_DIR / "fulltext".

    Retourne une chaîne vide en cas d'échec (best-effort).
    """
    if fetch is None:
        fetch = _default_fetch
    if cache_dir is None:
        cache_dir = config.CACHE_DIR / "fulltext"

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    path = _cache_path(url, cache_dir)
    if path.exists():
        return path.read_text(encoding="utf-8")

    try:
        html = fetch(url)
        text = trafilatura.extract(html) or ""
    except Exception:
        return ""

    # On ne met en cache que les extractions non vides pour permettre le retry
    # en cas d'échec transitoire (anti-bot, timeout, etc.).
    if text:
        path.write_text(text, encoding="utf-8")

    return text
