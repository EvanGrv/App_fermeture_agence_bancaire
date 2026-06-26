"""Schéma normalisé partagé par les providers de recherche."""
from __future__ import annotations


def normalize_result(raw: dict, source: str) -> dict:
    """Mappe un résultat brut (title/snippet/link...) vers le schéma article."""
    return {
        "titre": raw.get("title") or raw.get("titre") or "",
        "texte": raw.get("snippet") or raw.get("description") or raw.get("texte") or "",
        "url": raw.get("url") or raw.get("link") or "",
        "date": raw.get("date") or None,
        "source": source,
        "departement": None,
    }
