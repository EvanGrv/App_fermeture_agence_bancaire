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


def parse_ban(payload: dict, departement=None):
    """Renvoie {lat, lon, code_insee, departement} de la meilleure feature, ou None."""
    features = payload.get("features") or []
    if not features:
        return None
    expected = str(departement or "").strip()
    f = features[0]
    if expected:
        matched = None
        for candidate in features:
            props = candidate.get("properties", {}) or {}
            dep = _departement(props.get("citycode") or "", props.get("postcode") or "")
            if dep == expected:
                matched = candidate
                break
        if matched is None:
            return None
        f = matched
    lon, lat = f["geometry"]["coordinates"]
    props = f.get("properties", {}) or {}
    citycode = props.get("citycode") or ""
    postcode = props.get("postcode") or ""
    # `city` est la commune administrative ; pour un résultat de type municipality
    # elle est portée par `name`. On garde le rattachement administratif officiel.
    commune = props.get("city") or props.get("name") or None
    return {
        "lat": lat,
        "lon": lon,
        "code_insee": citycode or None,
        "departement": _departement(citycode, postcode),
        "commune": commune,
    }


def _url(commune: str, departement) -> str:
    # La BAN ne filtre pas par département sur /search municipality ;
    # on requête plusieurs résultats et parse_ban choisit le département attendu.
    params = {"q": commune, "type": "municipality", "limit": "5" if departement else "1"}
    return f"{_BASE}?{urllib.parse.urlencode(params)}"


def _url_adresse(adresse: str) -> str:
    # Géocodage à l'adresse complète (plus précis que la commune).
    return f"{_BASE}?{urllib.parse.urlencode({'q': adresse, 'limit': '1'})}"


def _lieu_variants(commune: str) -> list[str]:
    """Candidats prudents avant la recherche large BAN.

    Pour des mentions presse comme "Guer-Coëtquidan", la partie avant le tiret est
    parfois la commune administrative. On ne découpe que si le préfixe ressemble à
    une commune autonome ; on évite ainsi de transformer "Pont-de-Briques" en
    "Pont", ce qui serait pire que l'ambiguïté initiale.
    """
    variants: list[str] = []
    for sep in (" / ", " – ", " — "):
        if sep in commune:
            variants.append(commune.split(sep, 1)[0].strip())
    if "-" in commune:
        first = commune.split("-", 1)[0].strip()
        if len(first) >= 4 and first[0].isupper():
            variants.append(first)
    seen: set[str] = set()
    out: list[str] = []
    for value in variants:
        if value and value != commune and value not in seen:
            seen.add(value)
            out.append(value)
    return out


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
            resultat = parse_ban(fetch(_url(commune, departement)), departement)
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


def geocode_commune_ou_lieu(commune, departement=None, fetch=_default_fetch, cache=None, retries=2):
    """Géocode une commune avec repli sur une recherche large (lieu-dit/adresse).

    Beaucoup de localisations citées par la presse ne sont pas des communes
    administratives ("Coëtquidan", "Pont-de-Briques", "Montrapon"). La recherche
    `type=municipality` échoue alors. On retombe sur une recherche BAN large qui
    rattache le lieu à sa commune administrative (Coëtquidan -> Guer), tout en
    conservant `commune` = commune administrative officielle de la réponse.

    Best-effort : renvoie None si même la recherche large échoue.
    """
    geo = geocode_commune(commune, departement, fetch=fetch, cache=cache, retries=retries)
    if geo and geo.get("code_insee"):
        return geo
    if not commune:
        return None
    for variant in _lieu_variants(str(commune)):
        geo = geocode_commune(variant, departement, fetch=fetch, cache=cache, retries=retries)
        if geo and geo.get("code_insee"):
            return geo
    cle = f"lieu|{commune}|{departement or ''}"
    if cache is not None and cle in cache:
        return cache[cle]
    resultat = None
    for tentative in range(retries + 1):
        try:
            resultat = parse_ban(fetch(_url_adresse(commune)), departement)
            break
        except Exception as exc:
            if tentative < retries:
                time.sleep(0.5)
                continue
            print(f"[geocode] lieu {commune}: erreur {exc}")
            resultat = None
    if cache is not None:
        cache[cle] = resultat
    return resultat


def geocode_adresse(adresse, fetch=_default_fetch, cache=None, retries=2):
    """Géocode une adresse complète -> {lat, lon, code_insee, departement} | None."""
    if not adresse:
        return None
    if cache is not None and adresse in cache:
        return cache[adresse]
    resultat = None
    for tentative in range(retries + 1):
        try:
            resultat = parse_ban(fetch(_url_adresse(adresse)))
            break
        except Exception as exc:
            if tentative < retries:
                time.sleep(0.5)
                continue
            print(f"[geocode] {adresse}: erreur {exc}")
            resultat = None
    if cache is not None:
        cache[adresse] = resultat
    return resultat
