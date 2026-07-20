from backend.collectors import postal_web


def test_queries_couvrent_mairies_pappers_et_transformations():
    joined = "\n".join(postal_web.QUERIES)
    assert "conseil municipal" in joined
    assert "politique.pappers.fr" in joined
    assert "agence postale communale" in joined
    assert "relais poste" in joined


def test_collect_agrege_et_deduplique(monkeypatch):
    monkeypatch.setattr("config.POSTAL_WEB_MAX_QUERIES", 2)
    calls = []

    def search(query, limit=20):
        calls.append((query, limit))
        return [{
            "titre": "Le bureau de poste de Test va fermer", "extrait": "",
            "url": "https://mairie.test/poste", "date": "2026-07-01",
            "source": "Brave Search",
        }]

    articles = postal_web.collect(
        search_fn=search, queries=["q1", "q2", "q3"],
        news_fn=lambda queries: [],
    )
    assert len(calls) == 2
    assert len(articles) == 1
    assert articles[0]["canal"] == "postal_web"


def test_collect_utilise_google_news_sans_resultat_web(monkeypatch):
    monkeypatch.setattr("config.POSTAL_WEB_MAX_QUERIES", 2)
    calls = []

    def news(*, queries):
        calls.append(queries)
        return [{
            "titre": "Le bureau de poste sera transformé", "texte": "",
            "url": "https://presse.test/poste", "date": "2026-07-02",
            "source": "Google News",
        }]

    articles = postal_web.collect(
        search_fn=lambda query, limit=20: [],
        queries=["q1", "q2", "q3"], news_fn=news,
    )
    assert calls == [["q1", "q2"]]
    assert [article["url"] for article in articles] == ["https://presse.test/poste"]
