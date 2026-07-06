import hashlib
import re
import unicodedata


def normalise_cle(valeur: str) -> str:
    valeur = (valeur or "").replace("’", "'").replace("‘", "'")
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", valeur)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sans_accents.lower()).strip()


def closure_id(banque: str, commune: str, type_: str, adresse: str = "") -> str:
    parts = [normalise_cle(v) for v in (banque, commune, type_)]
    if adresse and adresse.strip():
        parts.append(normalise_cle(adresse))
    base = "|".join(parts)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
