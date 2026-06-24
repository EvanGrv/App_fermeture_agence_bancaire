from __future__ import annotations

import re

import config
from backend.dedup import normalise_cle

_COMMUNES_INVALIDES = {
    "",
    "inconnu",
    "inconnue",
    "non precise",
    "non precisee",
    "non renseigne",
    "non renseignee",
    "plusieurs communes",
    "communes rurales",
    "agences",
    "agence",
    "france",
}

def _cle_commune(commune: str | None) -> str:
    return re.sub(r"[-'’]", " ", normalise_cle(commune or ""))


_TERRITOIRES_NON_COMMUNES = {
    _cle_commune(v) for v in config.DEPARTEMENTS.values()
} | {
    "franche comte",
    "bourgogne franche comte",
    "haute loire",
    "loire haute loire",
    "normandie",
    "nouvelle aquitaine",
    "occitanie",
    "bretagne",
    "grand est",
    "hauts de france",
    "ile de france",
    "pays de la loire",
    "centre val de loire",
    "auvergne rhone alpes",
    "provence alpes cote d azur",
}


def _nettoie_commune(commune: str | None) -> str:
    return re.sub(r"\s+", " ", (commune or "").strip())


def commune_publiable(commune: str | None) -> bool:
    """True si la valeur ressemble à une commune nominative exploitable."""
    commune = _nettoie_commune(commune)
    cle = _cle_commune(commune)
    if cle in _COMMUNES_INVALIDES or cle in _TERRITOIRES_NON_COMMUNES:
        return False
    if len(commune) < 2:
        return False
    if re.search(r"\d+\s+(grandes?\s+)?villes?\b", cle):
        return False
    if re.search(r"\b(plusieurs|dix|vingt|reseau|region|departement|territoire|national)\b", cle):
        return False
    return True


def departement_valide(departement: str | None) -> bool:
    return bool(departement) and str(departement) in config.DEPARTEMENTS


def fermeture_publiable(closure: dict, geo: dict | None) -> tuple[bool, str | None]:
    """Valide qu'une fermeture peut être affichée comme agence localisée.

    Les articles non nominatifs restent utiles, mais doivent aller en vigilance
    plutôt que créer une agence fictive ou une commune approximative.
    """
    commune = closure.get("commune")
    if not commune_publiable(commune):
        return False, "commune absente, générique ou non nominative"
    if geo is None:
        return False, "commune non géocodée"
    geo_dep = geo.get("departement")
    dep = closure.get("departement")
    if dep and not departement_valide(dep):
        return False, f"département non codé ({dep})"
    if dep and geo_dep and str(dep) != str(geo_dep):
        return False, f"département incohérent ({dep} ≠ {geo_dep})"
    if not geo.get("code_insee"):
        return False, "code INSEE absent après géocodage"
    return True, None
