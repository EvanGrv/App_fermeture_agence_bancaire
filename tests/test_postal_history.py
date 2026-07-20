import config
from backend.collectors import postal_history


def test_backfill_inactif_sur_fenetre_quotidienne(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_NEWS_WHEN", "60d")
    assert postal_history.is_deep_run() is False
    assert postal_history.collect(
        news_fn=lambda **kwargs: (_ for _ in ()).throw(AssertionError()),
        search_fn=lambda *args, **kwargs: [],
    ) == []


def test_backfill_24_mois_decoupe_thematiques_et_couvre_departements(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_NEWS_WHEN", "720d")
    news_calls = []
    web_calls = []

    def news(**kwargs):
        news_calls.append(kwargs)
        return [{
            "titre": "Le bureau de poste ferme", "texte": "",
            "url": "https://example.test/fermeture", "date": "2025-01-01",
            "source": "Google News",
        }]

    def search(query, limit=20):
        web_calls.append(query)
        return []

    articles = postal_history.collect(news_fn=news, search_fn=search)
    assert postal_history.is_deep_run() is True
    assert news_calls[0]["slice_queries"] == set(postal_history.THEMATIC_QUERIES)
    assert len(news_calls[1]["queries"]) == len(config.DEPARTEMENTS)
    assert len(web_calls) == config.POSTAL_HISTORY_WEB_MAX_QUERIES
    assert len(articles) == 1
    assert articles[0]["canal"] == "postal_history"


def test_requetes_historiques_couvrent_les_impacts_lbp():
    joined = "\n".join(postal_history.THEMATIC_QUERIES)
    assert "fermeture définitive" in joined
    assert "agence postale communale" in joined
    assert "relais poste" in joined
    assert "services financiers" in joined
