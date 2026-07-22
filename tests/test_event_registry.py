from backend.collectors import event_registry


def _payload():
    return {
        "articles": {
            "pages": 1,
            "results": [{
                "title": "La Banque Postale perd un bureau",
                "body": "Le bureau de poste fermera définitivement.",
                "url": "https://example.fr/lbp",
                "dateTimePub": "2026-05-01T10:00:00Z",
                "source": {"title": "Le Journal local"},
            }],
        }
    }


def test_parse_response_normalise_article():
    article = event_registry.parse_response(_payload())[0]
    assert article["titre"] == "La Banque Postale perd un bureau"
    assert article["texte"].startswith("Le bureau de poste")
    assert article["source"] == "Le Journal local"
    assert article["canal"] == "event_registry"


def test_collect_envoie_fenetre_et_requete_booleenne():
    calls = []

    def fetch(payload):
        calls.append(payload)
        return _payload()

    articles = event_registry.collect(
        fetch=fetch,
        api_key="secret",
        since_date="2025-01-01",
        end_date="2026-01-01",
        max_pages=2,
    )

    assert len(articles) == 1
    assert calls[0]["dateStart"] == "2025-01-01"
    assert calls[0]["dateEnd"] == "2026-01-01"
    assert calls[0]["lang"] == "fra"
    assert "$and" in calls[0]["query"]["$query"]
    assert calls[0]["query"]["$query"]["$and"][0] == {
        "dateStart": "2025-01-01",
        "dateEnd": "2026-01-01",
    }


def test_collect_sans_cle_ou_quota_retourne_vide(monkeypatch):
    monkeypatch.setattr(event_registry.config, "EVENT_REGISTRY_API_KEY", "")
    assert event_registry.collect() == []
    assert event_registry.collect(
        fetch=lambda payload: {"error": "Insufficient tokens"},
        api_key="secret",
    ) == []
