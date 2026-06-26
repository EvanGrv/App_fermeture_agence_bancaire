import json

import pytest

from backend.search_providers import types, registry, brave, bing, local_sitemap


# --- types ------------------------------------------------------------------

def test_normalize_result_mappe_les_champs():
    raw = {"title": "T", "description": "D", "url": "https://x/1", "date": "2026-01-01"}
    out = types.normalize_result(raw, source="Brave")
    assert out == {"titre": "T", "texte": "D", "url": "https://x/1",
                   "date": "2026-01-01", "source": "Brave", "departement": None}


def test_normalize_result_accepte_link_et_snippet():
    raw = {"title": "T", "snippet": "S", "link": "https://x/2"}
    out = types.normalize_result(raw, source="X")
    assert out["texte"] == "S"
    assert out["url"] == "https://x/2"


# --- Brave ------------------------------------------------------------------

def test_brave_sans_cle_retourne_vide(monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    assert brave.search("BNP Bar-le-Duc") == []


def test_brave_parse_reponse(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    payload = {"web": {"results": [
        {"title": "BNP ferme à Bar-le-Duc", "description": "desc",
         "url": "https://estrepublicain.fr/a", "page_age": "2026-01-10"},
    ]}}
    out = brave.search("BNP Bar-le-Duc", fetch=lambda url, headers=None: payload)
    assert len(out) == 1
    assert out[0]["url"] == "https://estrepublicain.fr/a"
    assert out[0]["source"] == "Brave Search"


def test_brave_erreur_best_effort(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")

    def boom(url, headers=None):
        raise RuntimeError("HTTP 500")

    assert brave.search("q", fetch=boom) == []


# --- Bing -------------------------------------------------------------------

def test_bing_sans_cle_retourne_vide(monkeypatch):
    monkeypatch.delenv("BING_SEARCH_API_KEY", raising=False)
    assert bing.search("q") == []


def test_bing_parse_reponse(monkeypatch):
    monkeypatch.setenv("BING_SEARCH_API_KEY", "k")
    payload = {"webPages": {"value": [
        {"name": "CA Colmar", "snippet": "s", "url": "https://dna.fr/x",
         "dateLastCrawled": "2026-02-02T00:00:00Z"},
    ]}}
    out = bing.search("CA Colmar", fetch=lambda url, headers=None: payload)
    assert len(out) == 1
    assert out[0]["titre"] == "CA Colmar"
    assert out[0]["source"] == "Bing Search"


def test_bing_erreur_best_effort(monkeypatch):
    monkeypatch.setenv("BING_SEARCH_API_KEY", "k")

    def boom(url, headers=None):
        raise RuntimeError("nope")

    assert bing.search("q", fetch=boom) == []


# --- local_sitemap ----------------------------------------------------------

_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://estrepublicain.fr/bnp-paribas-bar-le-duc-ferme</loc>
       <lastmod>2026-01-10</lastmod></url>
  <url><loc>https://estrepublicain.fr/sport/match-de-foot</loc>
       <lastmod>2026-01-09</lastmod></url>
</urlset>
"""

_RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>BNP Paribas ferme son agence de Bar-le-Duc</title>
        <link>https://dna.fr/bnp-bar-le-duc</link>
        <pubDate>Mon, 12 Jan 2026 08:00:00 GMT</pubDate></item>
  <item><title>Recette de cuisine</title>
        <link>https://dna.fr/cuisine</link></item>
</channel></rss>
"""


@pytest.fixture(autouse=True)
def _sitemap_cache_propre():
    local_sitemap.clear_cache()
    yield
    local_sitemap.clear_cache()


def test_local_sitemap_desactive_par_defaut(monkeypatch):
    # Sans LOCAL_SITEMAP_ENABLED=1, le provider ne s'exécute pas (quotidien).
    monkeypatch.delenv("LOCAL_SITEMAP_ENABLED", raising=False)
    monkeypatch.setenv("LOCAL_SITEMAP_DOMAINS", "estrepublicain.fr")
    appels = []

    def fetch(url):
        appels.append(url)
        return _SITEMAP_XML

    assert local_sitemap.search("BNP Paribas Bar-le-Duc", fetch=fetch) == []
    assert appels == []


def test_local_sitemap_parse_xml_et_filtre(monkeypatch):
    monkeypatch.setenv("LOCAL_SITEMAP_ENABLED", "1")
    monkeypatch.setenv("LOCAL_SITEMAP_DOMAINS", "estrepublicain.fr")

    def fetch(url):
        if url.endswith("/sitemap.xml"):
            return _SITEMAP_XML
        raise RuntimeError("404")

    out = local_sitemap.search("BNP Paribas Bar-le-Duc", fetch=fetch)
    urls = [r["url"] for r in out]
    assert "https://estrepublicain.fr/bnp-paribas-bar-le-duc-ferme" in urls
    assert "https://estrepublicain.fr/sport/match-de-foot" not in urls


def test_local_sitemap_parse_rss(monkeypatch):
    monkeypatch.setenv("LOCAL_SITEMAP_ENABLED", "1")
    monkeypatch.setenv("LOCAL_SITEMAP_DOMAINS", "dna.fr")

    def fetch(url):
        if url.endswith("/rss.xml"):
            return _RSS_XML
        raise RuntimeError("404")

    out = local_sitemap.search("BNP Paribas Bar-le-Duc", fetch=fetch)
    titles = [r["titre"] for r in out]
    assert any("Bar-le-Duc" in t for t in titles)
    assert all("cuisine" not in (t or "").lower() for t in titles)


def test_local_sitemap_domaine_en_erreur_retourne_vide(monkeypatch):
    monkeypatch.setenv("LOCAL_SITEMAP_ENABLED", "1")
    monkeypatch.setenv("LOCAL_SITEMAP_DOMAINS", "panne.fr")

    def fetch(url):
        raise RuntimeError("DNS")

    assert local_sitemap.search("BNP", fetch=fetch) == []


def test_local_sitemap_cache_evite_refetch(monkeypatch):
    monkeypatch.setenv("LOCAL_SITEMAP_ENABLED", "1")
    monkeypatch.setenv("LOCAL_SITEMAP_DOMAINS", "estrepublicain.fr")
    appels = []

    def fetch(url):
        appels.append(url)
        if url.endswith("/sitemap.xml"):
            return _SITEMAP_XML
        raise RuntimeError("404")

    local_sitemap.search("BNP Paribas Bar-le-Duc", fetch=fetch)
    n_premier = len(appels)
    local_sitemap.search("BNP Paribas Bar-le-Duc", fetch=fetch)
    # Deuxième requête servie par le cache : aucun nouvel appel HTTP.
    assert len(appels) == n_premier


def test_local_sitemap_plafonne_le_nombre_de_domaines(monkeypatch):
    monkeypatch.setenv("LOCAL_SITEMAP_ENABLED", "1")
    monkeypatch.setenv("LOCAL_SITEMAP_DOMAINS", "a.fr,b.fr,c.fr,d.fr,e.fr")
    monkeypatch.setenv("LOCAL_SITEMAP_MAX_DOMAINS", "2")
    domaines_vus = set()

    def fetch(url):
        domaines_vus.add(url.split("/")[2])
        raise RuntimeError("404")

    local_sitemap.search("BNP Paribas Bar-le-Duc", fetch=fetch)
    assert domaines_vus == {"a.fr", "b.fr"}


def test_local_sitemap_priorise_domaine_site_dans_la_requete(monkeypatch):
    monkeypatch.setenv("LOCAL_SITEMAP_ENABLED", "1")
    monkeypatch.setenv("LOCAL_SITEMAP_DOMAINS", "ici.fr,actu.fr,dna.fr")
    monkeypatch.setenv("LOCAL_SITEMAP_MAX_DOMAINS", "1")
    domaines_vus = set()

    def fetch(url):
        domaines_vus.add(url.split("/")[2])
        raise RuntimeError("404")

    local_sitemap.search('site:dna.fr "Crédit Agricole" "Colmar"', fetch=fetch)
    assert domaines_vus == {"dna.fr"}


def test_local_sitemap_default_fetch_timeout(monkeypatch):
    monkeypatch.setenv("LOCAL_SITEMAP_TIMEOUT", "5")
    captured = {}

    class _Resp:
        text = "<urlset></urlset>"

        def raise_for_status(self):
            pass

    def fake_get(url, timeout=None, headers=None):
        captured["timeout"] = timeout
        return _Resp()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    local_sitemap._default_fetch("https://x.fr/sitemap.xml")
    assert captured["timeout"] == 5


# --- registry ---------------------------------------------------------------

def test_registry_combine_et_deduplique(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDERS", "fake_a,fake_b")

    art = {"titre": "T", "texte": "x", "url": "https://dup/1",
           "date": None, "source": "A", "departement": None}

    def fake_a(query, since=None, limit=10):
        return [art]

    def fake_b(query, since=None, limit=10):
        return [art, {"titre": "U", "texte": "y", "url": "https://uniq/2",
                      "date": None, "source": "B", "departement": None}]

    monkeypatch.setattr(registry, "PROVIDERS", {"fake_a": fake_a, "fake_b": fake_b})
    out = registry.search("q")
    urls = sorted(r["url"] for r in out)
    assert urls == ["https://dup/1", "https://uniq/2"]


def test_registry_provider_en_erreur_nignore_pas_les_autres(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDERS", "boom,ok")

    def boom(query, since=None, limit=10):
        raise RuntimeError("x")

    def ok(query, since=None, limit=10):
        return [{"titre": "T", "texte": "x", "url": "https://ok/1",
                 "date": None, "source": "ok", "departement": None}]

    monkeypatch.setattr(registry, "PROVIDERS", {"boom": boom, "ok": ok})
    out = registry.search("q")
    assert [r["url"] for r in out] == ["https://ok/1"]


def test_registry_provider_inconnu_ignore(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDERS", "inexistant")
    monkeypatch.setattr(registry, "PROVIDERS", {})
    assert registry.search("q") == []
