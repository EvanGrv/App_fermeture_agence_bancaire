import os
import time

import requests

SEARCH_URL = "https://recherche-entreprises.api.gouv.fr/search"
_LAST_REQUEST_AT = 0.0
_CACHE = {}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _default_fetch(url: str, **kwargs) -> dict:
    global _LAST_REQUEST_AT
    throttle = max(0.0, _float_env("SIRENE_THROTTLE_SECONDS", 1.2))
    elapsed = time.monotonic() - _LAST_REQUEST_AT
    if elapsed < throttle:
        time.sleep(throttle - elapsed)
    resp = requests.get(
        url,
        params=kwargs.get("params"),
        timeout=30,
        headers={"User-Agent": "veille-presse/1.0"},
    )
    _LAST_REQUEST_AT = time.monotonic()
    resp.raise_for_status()
    return resp.json()


def confirmer_fermeture(banque: str, commune: str, adresse: str | None = None,
                        fetch=_default_fetch) -> dict:
    """Contrôle a posteriori SIRENE, sans création de fermeture."""
    morceaux = [banque, commune, adresse]
    query = " ".join(m for m in morceaux if m)
    use_cache = fetch is _default_fetch
    if use_cache and query in _CACHE:
        return dict(_CACHE[query])
    retries = max(0, int(_float_env("SIRENE_MAX_RETRIES", 2)))
    wait = max(1.0, _float_env("SIRENE_RETRY_SECONDS", 8.0))
    try:
        for tentative in range(retries + 1):
            try:
                payload = fetch(SEARCH_URL, params={"q": query, "per_page": 1})
                break
            except requests.exceptions.HTTPError as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status != 429 or tentative >= retries:
                    raise
                response = getattr(exc, "response", None)
                retry_after = response.headers.get("Retry-After", "") if response is not None else ""
                try:
                    pause = max(wait, float(retry_after)) if retry_after else wait
                except ValueError:
                    pause = wait
                print(f"[controle] SIRENE quota temporaire — attente {pause:.0f}s")
                time.sleep(pause)
                wait *= 2
    except Exception as exc:
        print(f"[controle] SIRENE indisponible pour '{query}': {exc}")
        result = {"etat_administratif": None, "siret": None, "source": "SIRENE"}
        if use_cache:
            _CACHE[query] = result
        return dict(result)

    item = (payload.get("results") or [{}])[0]
    result = {
        "etat_administratif": item.get("etat_administratif"),
        "siret": item.get("siret"),
        "source": "SIRENE",
    }
    if use_cache:
        _CACHE[query] = result
    return dict(result)
