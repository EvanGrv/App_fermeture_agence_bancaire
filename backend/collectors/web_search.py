import os


def normalize_result(raw: dict) -> dict:
    """Normalise un résultat de recherche générique vers le schéma article.

    Mappe les champs courants (title, snippet/description, link/url, date)
    vers (titre, texte, url, date, source, departement).
    """
    return {
        "titre": raw.get("title", ""),
        "texte": raw.get("snippet") or raw.get("description", ""),
        "url": raw.get("link") or raw.get("url", ""),
        "date": raw.get("date", ""),
        "source": "Recherche web",
        "departement": None,
    }


def collect(fetch=None) -> list[dict]:
    """Scaffold collecteur web complémentaire.

    Les adaptateurs réels ne sont volontairement pas implémentés ici. Sans clé,
    ou même avec clé, ce module ne publie aucune donnée et ne fait aucun appel.
    """
    api_key = os.environ.get("WEB_SEARCH_API_KEY", "").strip()
    if not api_key:
        print("[web_search] WEB_SEARCH_API_KEY absente — collecteur inactif")
        return []

    # TODO: brancher un fournisseur (SerpAPI/Bing/Brave) ici
    print("[web_search] fournisseur non implémenté (clé détectée)")
    return []
