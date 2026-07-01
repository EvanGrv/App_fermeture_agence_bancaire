"""Construction du contexte compact envoyé à l'IA (Cycle 2b, section 10).

Sélectionne les unités (paragraphes, ou phrases si un seul bloc) contenant une
banque ou un terme de fermeture, préfixe des métadonnées, et plafonne la taille.
Aucune IA, aucun réseau.
"""
from __future__ import annotations

import config
from backend.prefilter import _ENSEIGNES_N, _TERMES_N, _normalise, _split_sentences


def _est_pertinent(unite: str) -> bool:
    n = _normalise(unite)
    return any(e in n for e in _ENSEIGNES_N) or any(t in n for t in _TERMES_N)


def _entete(article: dict) -> str:
    return (
        f"TITRE: {article.get('titre', '')}\n"
        f"SOURCE: {article.get('source', '')}\n"
        f"DATE: {article.get('date', '')}\n"
        f"URL: {article.get('url', '')}\n\n"
    )


def _tronquer(texte: str, limite: int) -> str:
    if len(texte) <= limite:
        return texte
    coupe = texte[:limite]
    dernier = max(coupe.rfind("."), coupe.rfind("\n"))
    return coupe[: dernier + 1] if dernier > 0 else coupe


def build_compact_context(article: dict, result, max_chars: int | None = None) -> str:
    max_chars = max_chars or config.PREFILTER_CONTEXT_MAX_CHARS
    entete = _entete(article)
    texte = article.get("texte", "") or ""
    budget_corps = max(0, max_chars - len(entete))

    # Cas court : tout le corps tient -> on l'envoie tel quel (aucune perte).
    if len(texte) <= budget_corps:
        return _tronquer(entete + texte, max_chars)

    # Sélection des unités pertinentes.
    paragraphes = [p.strip() for p in texte.split("\n\n") if p.strip()]
    if len(paragraphes) > 1:
        unites = paragraphes
        sep = "\n\n"
    else:
        unites = _split_sentences(texte)
        sep = " "

    gardees = [u for u in unites if _est_pertinent(u)]
    corps = sep.join(gardees) if gardees else texte  # repli : texte brut

    return _tronquer(entete + corps, max_chars)
