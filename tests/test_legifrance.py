import json
from pathlib import Path

import requests

from backend.collectors import legifrance

FIXT = Path(__file__).parent / "fixtures" / "legifrance_search_sample.json"


def test_collect_sans_credentials_retourne_vide(monkeypatch):
    legifrance._AUTH_DISABLED_REASON = None
    monkeypatch.delenv("LEGIFRANCE_CLIENT_ID", raising=False)
    monkeypatch.delenv("LEGIFRANCE_CLIENT_SECRET", raising=False)
    assert legifrance.collect(fetch=lambda *a, **kw: {}) == []


def test_collect_parse_articles(monkeypatch):
    legifrance._AUTH_DISABLED_REASON = None
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.delenv("LEGIFRANCE_ENV", raising=False)
    appels = []

    def fetch(url, **kwargs):
        appels.append((url, kwargs))
        if url == legifrance.TOKEN_URL:
            assert kwargs["data"]["scope"] == "openid searchUsingPOST"
            return {"access_token": "tok"}
        assert kwargs["headers"]["Authorization"] == "Bearer tok"
        assert kwargs["json"]["fond"] == "ALL"
        assert kwargs["json"]["recherche"]["typePagination"] == "DEFAUT"
        assert kwargs["json"]["recherche"]["sort"] == "PERTINENCE"
        criteres = kwargs["json"]["recherche"]["champs"][0]["criteres"]
        assert criteres[0] == {
            "valeur": "Banque Populaire",
            "operateur": "ET",
            "typeRecherche": "EXACTE",
        }
        return json.loads(FIXT.read_text(encoding="utf-8"))

    articles = legifrance.collect(fetch=fetch, queries=["Banque Populaire fermeture agence"])
    assert len(articles) == 2
    assert articles[0]["titre"] == "Accord relatif au PSE de Banque Populaire Grand Ouest"
    assert "fermeture" in articles[0]["texte"]
    assert articles[0]["url"].startswith("https://www.legifrance.gouv.fr")
    assert articles[0]["date"] == "2026-03-15"
    assert articles[0]["source"] == "Légifrance"
    assert articles[0]["departement"] is None
    assert len(appels) == 2


def test_collect_supporte_sandbox(monkeypatch):
    legifrance._AUTH_DISABLED_REASON = None
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("LEGIFRANCE_ENV", "sandbox")
    urls = []

    def fetch(url, **kwargs):
        urls.append(url)
        if url == legifrance.SANDBOX_TOKEN_URL:
            return {"access_token": "tok"}
        return {"results": []}

    assert legifrance.collect(fetch=fetch, queries=["CCF PSE"]) == []
    assert urls == [legifrance.SANDBOX_TOKEN_URL, legifrance.SANDBOX_SEARCH_URL]


def test_token_fallback_sans_scope(monkeypatch):
    legifrance._AUTH_DISABLED_REASON = None
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("LEGIFRANCE_ENV", "prod")
    calls = []

    def fetch(url, **kwargs):
        calls.append(kwargs)
        if url == legifrance.TOKEN_URL and "scope" in kwargs["data"]:
            response = requests.Response()
            response.status_code = 400
            raise requests.exceptions.HTTPError(response=response)
        if url == legifrance.TOKEN_URL:
            return {"access_token": "tok"}
        return {"results": []}

    assert legifrance.collect(fetch=fetch, queries=["CCF PSE"]) == []
    assert len([call for call in calls if call.get("data", {}).get("grant_type") == "client_credentials"]) == 3


def test_token_scope_configurable(monkeypatch):
    legifrance._AUTH_DISABLED_REASON = None
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("LEGIFRANCE_ENV", "prod")
    monkeypatch.setenv("LEGIFRANCE_SCOPE", "openid crossSearchUsingPOST")
    scopes = []

    def fetch(url, **kwargs):
        if url == legifrance.TOKEN_URL:
            scopes.append(kwargs["data"]["scope"])
            return {"access_token": "tok"}
        return {"results": []}

    assert legifrance.collect(fetch=fetch, queries=["CCF PSE"]) == []
    assert scopes == ["openid crossSearchUsingPOST"]


def test_collect_plafonne_les_requetes(monkeypatch):
    legifrance._AUTH_DISABLED_REASON = None
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("LEGIFRANCE_ENV", "prod")
    monkeypatch.setenv("LEGIFRANCE_MAX_QUERIES", "1")
    recherches = []

    def fetch(url, **kwargs):
        if url == legifrance.TOKEN_URL:
            return {"access_token": "tok"}
        criteres = kwargs["json"]["recherche"]["champs"][0]["criteres"]
        recherches.append(criteres[0]["valeur"])
        return {"results": []}

    assert legifrance.collect(fetch=fetch, queries=["q1", "q2"]) == []
    assert recherches == ["q1"]


def test_articles_recupere_extraits_sections():
    payload = {
        "results": [{
            "titles": [{"id": "JORFTEXT1", "title": "Accord test"}],
            "sections": [{"extracts": [{"values": ["<mark>fermeture</mark> agence"]}]}],
        }]
    }
    articles = legifrance._articles(payload)
    assert articles[0]["titre"] == "Accord test"
    assert articles[0]["texte"] == "fermeture agence"
    assert articles[0]["url"].endswith("/JORFTEXT1")
