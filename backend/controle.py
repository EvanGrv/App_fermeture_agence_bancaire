import requests

SEARCH_URL = "https://recherche-entreprises.api.gouv.fr/search"


def _default_fetch(url: str, **kwargs) -> dict:
    resp = requests.get(
        url,
        params=kwargs.get("params"),
        timeout=30,
        headers={"User-Agent": "veille-presse/1.0"},
    )
    resp.raise_for_status()
    return resp.json()


def confirmer_fermeture(banque: str, commune: str, adresse: str | None = None,
                        fetch=_default_fetch) -> dict:
    """Contrôle a posteriori SIRENE, sans création de fermeture."""
    morceaux = [banque, commune, adresse]
    query = " ".join(m for m in morceaux if m)
    try:
        payload = fetch(SEARCH_URL, params={"q": query, "per_page": 1})
    except Exception as exc:
        print(f"[controle] SIRENE indisponible: {exc}")
        return {"etat_administratif": None, "siret": None, "source": "SIRENE"}

    item = (payload.get("results") or [{}])[0]
    return {
        "etat_administratif": item.get("etat_administratif"),
        "siret": item.get("siret"),
        "source": "SIRENE",
    }
