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
    "centre val",
    "haute loire",
    "haute vienne",
    "antilles guyane",
    "regions",
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


# Faux candidats fréquents extraits du texte d'un article : noms de médias /
# journaux, génériques ("L'agence"), articles ou mots-outils en tête de phrase.
# Ils ne doivent jamais partir en géocodage BAN comme s'ils étaient des communes.
_MEDIAS_ET_SOURCES = {
    "ouest france", "est republicain", "l est republicain",
    "la nouvelle republique", "nouvelle republique", "le bien public",
    "bien public", "info chalon", "delta fm", "europe says", "europesays",
    "dna", "ici", "actu", "le progres", "le dauphine", "sud ouest",
    "la voix", "la voix du nord", "france bleu", "radio france", "le republicain lorrain",
    "republicain lorrain", "paris normandie", "la depeche", "le telegramme",
    "le parisien", "le monde", "le figaro", "la montagne", "l eveil",
    "eveil", "l echo republicain", "echo republicain", "le berry republicain",
    "berry republicain", "la commere", "nord littoral", "france 3 regions",
    "centre presse aveyron", "le populaire", "le populaire du centre",
    "outre mer la", "outre mer", "paris norm", "afp", "reuters",
}
_GENERIQUES = {
    "l agence", "agence", "la banque", "banque", "le", "la", "les", "un",
    "une", "des", "du", "de", "en", "au", "aux", "dans", "cette", "ce",
    "ces", "son", "sa", "ses", "et", "ou", "mais", "ledit", "selon",
    "apres", "après", "pourquoi", "sept", "trois", "fermeture",
    "fermetures", "centre", "sud", "pays", "hexagone", "caisse",
    "epargne", "épargne", "tout", "vers", "six",
}
_FAUX_CANDIDATS = _MEDIAS_ET_SOURCES | _GENERIQUES


def _nettoie_commune(commune: str | None) -> str:
    return re.sub(r"\s+", " ", (commune or "").strip())


def commune_publiable(commune: str | None) -> bool:
    """True si la valeur ressemble à une commune nominative exploitable."""
    commune = _nettoie_commune(commune)
    cle = _cle_commune(commune)
    if cle in _COMMUNES_INVALIDES or cle in _TERRITOIRES_NON_COMMUNES:
        return False
    if cle in _FAUX_CANDIDATS:
        return False
    # Mots-outils / fragments trop courts (≤2 lettres, hors quelques communes
    # réelles très courtes qui restent gérées par le géocodage en aval) : on
    # exige une longueur minimale pour un candidat extrait du texte brut.
    if len(commune) < 3:
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
