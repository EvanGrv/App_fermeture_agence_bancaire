"""Couche providers de recherche web (Phase 6).

Chaque provider expose `search(query, since=None, limit=10) -> list[dict]` et
renvoie des articles au format normalisé (cf. `types.normalize_result`).
Best-effort : sans clé/configuration, ou en cas d'erreur, un provider renvoie [].
Le `registry` agrège les providers actifs et déduplique par URL.
"""
