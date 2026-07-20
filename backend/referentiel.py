import csv
import hashlib
import io
from pathlib import Path

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


def _default_text_fetch(url: str, **kwargs) -> str:
    resp = requests.get(
        url,
        timeout=kwargs.get("timeout", 60),
        headers={"User-Agent": "veille-presse/1.0"},
    )
    resp.raise_for_status()
    return resp.text


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


def _norm_header(value: str) -> str:
    return normalise_cle(value or "").replace(" ", "_")


def _first(row: dict, aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = row.get(alias)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _float_fr(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def _read_csv_text(source: str | Path | None, fetch) -> str | None:
    if source:
        source_s = str(source)
        if source_s.startswith(("http://", "https://")):
            return fetch(source_s)
        p = Path(source_s)
        if p.exists():
            return p.read_text(encoding="utf-8-sig")
        return None
    if getattr(config, "LBP_AGENCES_CSV_URL", ""):
        return fetch(config.LBP_AGENCES_CSV_URL)
    cache = Path(getattr(config, "LBP_AGENCES_CACHE", config.CACHE_DIR / "lbp_agences.csv"))
    if cache.exists():
        return cache.read_text(encoding="utf-8-sig")
    return None


def _csv_rows(text: str) -> list[dict]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = []
    for raw in reader:
        rows.append({_norm_header(k): (v or "").strip() for k, v in raw.items() if k})
    return rows


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


def fetch_lbp_agences(source: str | Path | None = None, fetch=_default_text_fetch) -> list[dict]:
    """Charge un référentiel CSV La Banque Postale / bureaux La Poste bancarisés.

    Le CSV peut venir de `LBP_AGENCES_CSV_URL`, de `data/cache/lbp_agences.csv`
    ou d'un chemin explicite. Les noms de colonnes sont volontairement tolérants
    pour accepter une extraction open data ou un export manuel.

    Cette source alimente uniquement le référentiel d'agences. Elle ne crée
    jamais de fermeture.
    """
    try:
        text = _read_csv_text(source, fetch)
    except Exception as exc:
        print(f"[referentiel] La Banque Postale indisponible: {exc}")
        return []
    if not text:
        return []

    branches = []
    for row in _csv_rows(text):
        code_postal = _first(row, (
            "code_postal", "cp", "postcode", "addr_postcode", "codepostal",
        ))
        commune = _first(row, (
            "commune", "localite", "ville", "libelle_commune", "nom_commune",
            "addr_city",
        ))
        nom = _first(row, (
            "nom", "libelle", "libelle_du_site", "bureau", "etablissement",
            "name",
        ))
        identifiant = _first(row, (
            "id", "identifiant", "code", "code_site", "code_etablissement",
            "siret", "osm_id",
        ))
        adresse = _first(row, (
            "adresse", "adresse_complete", "ligne_adresse", "addr_street",
        ))
        lat = _float_fr(_first(row, ("lat", "latitude", "y", "geo_point_2d_lat")))
        lon = _float_fr(_first(row, ("lon", "lng", "longitude", "x", "geo_point_2d_lon")))
        if lat is None or lon is None:
            geo = _first(row, ("geo_point_2d", "coordonnees", "coordonnees_geo"))
            if geo and "," in geo:
                left, right = [part.strip() for part in geo.split(",", 1)]
                lat = lat if lat is not None else _float_fr(left)
                lon = lon if lon is not None else _float_fr(right)
        if not (commune or code_postal or adresse or identifiant):
            continue
        key = identifiant or "|".join([nom, adresse, code_postal, commune])
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        branches.append({
            "banque": "La Banque Postale",
            "commune": commune or None,
            "code_postal": code_postal or None,
            "departement": _departement(code_postal),
            "lat": lat,
            "lon": lon,
            "osm_id": f"lbp/{digest}",
            "source": "La Banque Postale",
        })
    return branches


def compter_par_departement(branches: list[dict]) -> dict[str, int]:
    compteur = {}
    for branche in branches:
        dep = branche.get("departement")
        if dep:
            compteur[dep] = compteur.get(dep, 0) + 1
    return compteur
