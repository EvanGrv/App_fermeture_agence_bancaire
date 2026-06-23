# backend/geojson.py
from pathlib import Path
import requests
import config

# GeoJSON simplifié des départements français (france-geojson, G. David).
SOURCE_URL = (
    "https://raw.githubusercontent.com/gregoiredavid/france-geojson/"
    "master/departements-version-simplifiee.geojson"
)


def _default_fetch(url: str) -> str:
    resp = requests.get(url, timeout=60, headers={"User-Agent": "veille-presse/1.0"})
    resp.raise_for_status()
    return resp.text


def ensure_departements_geojson(path=config.GEOJSON_PATH, fetch=_default_fetch) -> Path:
    path = Path(path)
    if path.exists():
        return path
    contenu = fetch(SOURCE_URL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenu, encoding="utf-8")
    return path
