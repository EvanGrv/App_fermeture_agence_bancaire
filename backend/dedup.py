import hashlib
import re
import unicodedata


def normalise_cle(valeur: str) -> str:
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", valeur)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sans_accents.lower()).strip()


def closure_id(banque: str, commune: str, type_: str) -> str:
    base = "|".join(normalise_cle(v) for v in (banque, commune, type_))
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
