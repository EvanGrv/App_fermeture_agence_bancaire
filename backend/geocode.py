import time
import urllib.parse
import requests

_BASE = "https://api-adresse.data.gouv.fr/search/"


def _departement(citycode: str, postcode: str):
    src = (citycode or postcode or "").strip()
    if not src:
        return None
    if src[:2] in ("97", "98"):            # DROM (971-976)
        return src[:3]
    if src[:2].upper() in ("2A", "2B"):    # Corse (code INSEE)
        return src[:2].upper()
    return src[:2] if src[:2].isdigit() else None


def parse_ban(payload: dict):
    """Renvoie {lat, lon, code_insee, departement} de la 1re feature, ou None."""
    features = payload.get("features") or []
    if not features:
        return None
    f = features[0]
    lon, lat = f["geometry"]["coordinates"]
    props = f.get("properties", {}) or {}
    citycode = props.get("citycode") or ""
    postcode = props.get("postcode") or ""
    return {
        "lat": lat,
        "lon": lon,
        "code_insee": citycode or None,
        "departement": _departement(citycode, postcode),
    }


def _url(commune: str, departement) -> str:
    # La BAN ne filtre pas par département sur /search municipality ;
    # on requête la commune et on prend le 1er résultat (limit=1).
    params = {"q": commune, "type": "municipality", "limit": "1"}
    return f"{_BASE}?{urllib.parse.urlencode(params)}"


def _default_fetch(url: str) -> dict:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "veille-presse/1.0"})
    resp.raise_for_status()
    return resp.json()


def geocode_commune(commune, departement=None, fetch=_default_fetch, cache=None, retries=2):
    if not commune:
        return None
    cle = f"{commune}|{departement or ''}"
    if cache is not None and cle in cache:
        return cache[cle]
    resultat = None
    for tentative in range(retries + 1):
        try:
            resultat = parse_ban(fetch(_url(commune, departement)))
            break
        except Exception as exc:
            if tentative < retries:
                time.sleep(0.5)
                continue
            print(f"[geocode] {commune}: erreur {exc}")
            resultat = None
    if cache is not None:
        cache[cle] = resultat
    return resultat
