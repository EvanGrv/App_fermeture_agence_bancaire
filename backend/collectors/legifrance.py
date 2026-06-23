import os
import time

import requests

import config

TOKEN_URL = "https://oauth.piste.gouv.fr/api/oauth/token"
SEARCH_URL = "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/search"
BASE_URL = "https://www.legifrance.gouv.fr"


def _queries() -> list[str]:
    termes = "(fermeture OR PSE OR restructuration OR suppression agences)"
    return [f"{banque} {termes}" for banque in config.ENSEIGNES]


QUERIES = _queries()


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
    resp.raise_for_status()
    return resp.json()


def _token(fetch, client_id: str, client_secret: str) -> str | None:
    payload = fetch(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "openid",
        },
    )
    return payload.get("access_token")


def _titre(item: dict) -> str:
    titles = item.get("titles") or []
    if titles and isinstance(titles[0], dict):
        return titles[0].get("title") or ""
    return item.get("title") or item.get("name") or ""


def _texte(item: dict) -> str:
    return item.get("text") or item.get("content") or item.get("summary") or ""


def _date(item: dict) -> str:
    return item.get("date") or item.get("publicationDate") or item.get("datePublication") or ""


def _url(item: dict) -> str:
    if item.get("url"):
        return item["url"]
    ident = item.get("id") or item.get("cid")
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

    try:
        token = _token(fetch, client_id, client_secret)
    except Exception as exc:
        print(f"[legifrance] authentification en erreur: {exc}")
        return []
    if not token:
        print("[legifrance] authentification sans token, collecteur désactivé")
        return []

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resultats = []
    vus = set()
    for query in queries:
        try:
            payload = fetch(SEARCH_URL, headers=headers, json={"query": query})
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
            time.sleep(1)
    return resultats
