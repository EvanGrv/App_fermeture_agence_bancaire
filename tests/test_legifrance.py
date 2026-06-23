import json
from pathlib import Path

from backend.collectors import legifrance

FIXT = Path(__file__).parent / "fixtures" / "legifrance_search_sample.json"


def test_collect_sans_credentials_retourne_vide(monkeypatch):
    monkeypatch.delenv("LEGIFRANCE_CLIENT_ID", raising=False)
    monkeypatch.delenv("LEGIFRANCE_CLIENT_SECRET", raising=False)
    assert legifrance.collect(fetch=lambda *a, **kw: {}) == []


def test_collect_parse_articles(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.delenv("LEGIFRANCE_ENV", raising=False)
    appels = []

    def fetch(url, **kwargs):
        appels.append((url, kwargs))
        if url == legifrance.TOKEN_URL:
            return {"access_token": "tok"}
        assert kwargs["headers"]["Authorization"] == "Bearer tok"
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


def test_collect_plafonne_les_requetes(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("LEGIFRANCE_MAX_QUERIES", "1")
    recherches = []

    def fetch(url, **kwargs):
        if url == legifrance.TOKEN_URL:
            return {"access_token": "tok"}
        recherches.append(kwargs["json"]["query"])
        return {"results": []}

    assert legifrance.collect(fetch=fetch, queries=["q1", "q2"]) == []
    assert recherches == ["q1"]
