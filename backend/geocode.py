import urllib.parse
import requests

_BASE = "https://api-adresse.data.gouv.fr/search/"


def parse_ban(payload: dict):
    features = payload.get("features") or []
    if not features:
        return None
    lon, lat = features[0]["geometry"]["coordinates"]
    return (lat, lon)


def _url(commune: str, departement) -> str:
    # La BAN ne filtre pas par département sur /search municipality ;
    # on requête la commune et on prend le 1er résultat (limit=1).
    params = {"q": commune, "type": "municipality", "limit": "1"}
    return f"{_BASE}?{urllib.parse.urlencode(params)}"


def _default_fetch(url: str) -> dict:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "veille-presse/1.0"})
    resp.raise_for_status()
    return resp.json()


def geocode_commune(commune, departement=None, fetch=_default_fetch, cache=None):
    if not commune:
        return None
    cle = f"{commune}|{departement or ''}"
    if cache is not None and cle in cache:
        return cache[cle]
    try:
        payload = fetch(_url(commune, departement))
        coords = parse_ban(payload)
    except Exception as exc:
        print(f"[geocode] {commune}: erreur {exc}")
        coords = None
    if cache is not None:
        cache[cle] = coords
    return coords
