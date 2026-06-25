import unicodedata
import config


def _normalise(texte: str) -> str:
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn"
    )
    return sans_accents.lower()


_VARIANTES = config.ENSEIGNES + [
    v for vs in getattr(config, "MARQUES_REGIONALES", {}).values() for v in vs
]
_ENSEIGNES_N = [_normalise(e) for e in _VARIANTES]
_TERMES_N = [_normalise(t) for t in config.TERMES_FERMETURE]


def is_relevant(article: dict) -> bool:
    contenu = _normalise(f"{article.get('titre', '')} {article.get('texte', '')}")
    a_enseigne = any(e in contenu for e in _ENSEIGNES_N)
    a_terme = any(t in contenu for t in _TERMES_N)
    return a_enseigne and a_terme
