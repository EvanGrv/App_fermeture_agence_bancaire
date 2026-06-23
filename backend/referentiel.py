import requests

import config
from backend.dedup import normalise_cle

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

_OVERPASS_QUERY = """
[out:json][timeout:180];
area["ISO3166-1"="FR"][admin_level=2]->.france;
(
  node["amenity"="bank"](area.france);
  way["amenity"="bank"](area.france);
  relation["amenity"="bank"](area.france);
  node["office"="financial"](area.france);
  way["office"="financial"](area.france);
  relation["office"="financial"](area.france);
);
out center tags;
"""


def _default_fetch(url: str, **kwargs) -> dict:
    resp = requests.post(
        url,
        data=kwargs.get("data"),
        timeout=180,
        headers={"User-Agent": "veille-presse/1.0"},
    )
    resp.raise_for_status()
    return resp.json()


def _departement(code_postal: str | None) -> str | None:
    if not code_postal:
        return None
    code = str(code_postal).strip()
    if len(code) < 2:
        return None
    if code.startswith("97") or code.startswith("98"):
        return code[:3] if len(code) >= 3 else None
    if code.startswith("20"):
        return None
    return code[:2]


def _coordonnees(element: dict) -> tuple[float | None, float | None]:
    if "lat" in element and "lon" in element:
        return element.get("lat"), element.get("lon")
    center = element.get("center") or {}
    return center.get("lat"), center.get("lon")


def _banque(tags: dict) -> str:
    return (tags.get("operator") or tags.get("brand") or tags.get("name") or "").strip()


def _est_exclue(banque: str) -> bool:
    return normalise_cle(banque) in getattr(config, "EXCLURE_BANQUES", [])


def fetch_osm_banques(fetch=_default_fetch) -> list[dict]:
    """Charge les agences bancaires OSM/Overpass en France.

    Ce référentiel sert de dénominateur et de contrôle, jamais d'annonce de fermeture.
    """
    try:
        payload = fetch(OVERPASS_URL, data={"data": _OVERPASS_QUERY})
    except Exception as exc:
        print(f"[referentiel] Overpass indisponible: {exc}")
        return []

    branches = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        banque = _banque(tags)
        if not banque or _est_exclue(banque):
            continue
        lat, lon = _coordonnees(element)
        code_postal = tags.get("addr:postcode")
        branches.append({
            "banque": banque,
            "commune": tags.get("addr:city"),
            "code_postal": code_postal,
            "departement": _departement(code_postal),
            "lat": lat,
            "lon": lon,
            "osm_id": f"{element.get('type')}/{element.get('id')}",
            "source": "OSM",
        })
    return branches


def compter_par_departement(branches: list[dict]) -> dict[str, int]:
    compteur = {}
    for branche in branches:
        dep = branche.get("departement")
        if dep:
            compteur[dep] = compteur.get(dep, 0) + 1
    return compteur
