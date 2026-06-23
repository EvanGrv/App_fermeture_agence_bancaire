import os
import re
import time

import requests

import config

TOKEN_URL = "https://oauth.piste.gouv.fr/api/oauth/token"
SEARCH_URL = "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/search"
SANDBOX_TOKEN_URL = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
SANDBOX_SEARCH_URL = "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app/search"
BASE_URL = "https://www.legifrance.gouv.fr"


def _queries() -> list[str]:
    termes = ["fermeture agence", "PSE restructuration", "suppression agences"]
    return [f"{banque} {terme}" for banque in config.ENSEIGNES for terme in termes]


QUERIES = _queries()
DEFAULT_THROTTLE_SECONDS = 2.0
DEFAULT_MAX_QUERIES = 8
DEFAULT_PAGE_SIZE = 5


def _default_fetch(url: str, **kwargs) -> dict:
    method = kwargs.get("method", "POST")
    resp = requests.request(
        method,
        url,
        json=kwargs.get("json"),
        data=kwargs.get("data"),
        headers=kwargs.get("headers"),
        timeout=30,
    )
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        try:
            attente = min(float(retry_after), 60) if retry_after else 30
        except ValueError:
            attente = 30
        print(f"[legifrance] quota atteint — attente {attente:g}s")
        time.sleep(attente)
        resp = requests.request(
            method,
            url,
            json=kwargs.get("json"),
            data=kwargs.get("data"),
            headers=kwargs.get("headers"),
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


def _urls() -> tuple[str, str]:
    env = os.environ.get("LEGIFRANCE_ENV", "prod").strip().lower()
    if env == "sandbox":
        return SANDBOX_TOKEN_URL, SANDBOX_SEARCH_URL
    return TOKEN_URL, SEARCH_URL


def _token(fetch, client_id: str, client_secret: str, token_url: str) -> str | None:
    payload = fetch(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "openid",
        },
    )
    return payload.get("access_token")


def _search_payload(query: str) -> dict:
    criteres = _criteres(query)
    return {
        "fond": "ALL",
        "recherche": {
            "champs": [{
                "typeChamp": "ALL",
                "operateur": "ET",
                "criteres": criteres,
            }],
            "operateur": "ET",
            "pageNumber": 1,
            "pageSize": max(1, min(100, _int_env("LEGIFRANCE_PAGE_SIZE", DEFAULT_PAGE_SIZE))),
            "sort": "PERTINENCE",
            "typePagination": "DEFAUT",
        },
    }


def _criteres(query: str) -> list[dict]:
    for banque in sorted(config.ENSEIGNES, key=len, reverse=True):
        prefix = f"{banque} "
        if query.lower().startswith(prefix.lower()):
            reste = query[len(prefix):].strip()
            criteres = [{
                "valeur": banque,
                "operateur": "ET",
                "typeRecherche": "EXACTE",
            }]
            if reste:
                criteres.append({
                    "valeur": reste,
                    "operateur": "ET",
                    "typeRecherche": "TOUS_LES_MOTS_DANS_UN_CHAMP",
                })
            return criteres
    return [{
        "valeur": query,
        "operateur": "ET",
        "typeRecherche": "TOUS_LES_MOTS_DANS_UN_CHAMP",
    }]


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _titre(item: dict) -> str:
    titles = item.get("titles") or []
    if titles and isinstance(titles[0], dict):
        return titles[0].get("title") or ""
    return item.get("title") or item.get("name") or ""


def _texte(item: dict) -> str:
    morceaux = []
    for key in ("text", "content", "summary", "descriptionFusionHtml"):
        if item.get(key):
            morceaux.append(item[key])
    for key in ("resumePrincipal", "autreResume", "motsCles"):
        if item.get(key):
            morceaux.extend(item[key])
    for section in item.get("sections") or []:
        for extract in section.get("extracts") or []:
            morceaux.extend(extract.get("values") or [])
    return _nettoie_html(" ".join(str(m) for m in morceaux if m))


def _nettoie_html(texte: str) -> str:
    return re.sub(r"<[^>]+>", "", texte or "").strip()


def _date(item: dict) -> str:
    return item.get("date") or item.get("publicationDate") or item.get("datePublication") or ""


def _url(item: dict) -> str:
    if item.get("url"):
        return item["url"]
    titles = item.get("titles") or []
    ident = item.get("id") or item.get("cid")
    if not ident and titles and isinstance(titles[0], dict):
        ident = titles[0].get("id") or titles[0].get("cid")
    return f"{BASE_URL}/jorf/id/{ident}" if ident else BASE_URL


def _articles(payload: dict) -> list[dict]:
    items = payload.get("results") or payload.get("items") or []
    articles = []
    for item in items:
        articles.append({
            "titre": _titre(item),
            "texte": _texte(item),
            "url": _url(item),
            "date": _date(item),
            "source": "Légifrance",
            "departement": None,
        })
    return articles


def collect(fetch=_default_fetch, queries=QUERIES) -> list[dict]:
    client_id = os.environ.get("LEGIFRANCE_CLIENT_ID")
    client_secret = os.environ.get("LEGIFRANCE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("[legifrance] credentials absents, collecteur désactivé")
        return []

    token_url, search_url = _urls()
    try:
        token = _token(fetch, client_id, client_secret, token_url)
    except Exception as exc:
        print(f"[legifrance] authentification en erreur: {exc}")
        return []
    if not token:
        print("[legifrance] authentification sans token, collecteur désactivé")
        return []

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resultats = []
    vus = set()
    max_queries = max(0, _int_env("LEGIFRANCE_MAX_QUERIES", DEFAULT_MAX_QUERIES))
    throttle = max(0.0, _float_env("LEGIFRANCE_THROTTLE_SECONDS", DEFAULT_THROTTLE_SECONDS))
    for query in list(queries)[:max_queries]:
        try:
            payload = fetch(search_url, headers=headers, json=_search_payload(query))
        except Exception as exc:
            print(f"[legifrance] requête '{query}': erreur {exc}")
            continue
        for art in _articles(payload):
            url = art.get("url") or ""
            if url and url in vus:
                continue
            if url:
                vus.add(url)
            resultats.append(art)
        if fetch is _default_fetch:
            time.sleep(throttle)
    return resultats
