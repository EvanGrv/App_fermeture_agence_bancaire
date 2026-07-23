from datetime import date

from backend.collectors import mediacloud


class FakeClient:
    def __init__(self):
        self.calls = []

    def story_list(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if len(self.calls) == 1:
            return ([{
                "title": "Une agence bancaire fermera à Tours",
                "url": "https://example.fr/tours",
                "publish_date": "2026-06-10",
                "media_name": "example.fr",
            }], "next-page")
        return ([{
            "title": "Le bureau de poste va fermer",
            "url": "https://example.fr/poste",
            "indexed_date": "2026-06-11T08:00:00Z",
            "media_url": "example.fr",
        }], None)


def test_collect_pages_et_normalise():
    client = FakeClient()
    articles = mediacloud.collect(
        client=client,
        api_key="",
        since_date="2025-01-01",
        end_date="2026-01-01",
        max_pages=2,
        max_articles=10,
    )

    assert len(articles) == 2
    assert articles[0] == {
        "titre": "Une agence bancaire fermera à Tours",
        "texte": "",
        "url": "https://example.fr/tours",
        "date": "2026-06-10",
        "source": "example.fr",
        "departement": None,
        "canal": "mediacloud",
    }
    assert "language:fr" in client.calls[0][0]
    assert client.calls[0][1]["start_date"] == date(2025, 1, 1)
    assert client.calls[0][1]["end_date"] == date(2026, 1, 1)
    assert client.calls[0][1]["collection_ids"] == [34412146, 38379799]
    assert client.calls[0][1]["page_size"] == 10
    assert client.calls[1][1]["pagination_token"] == "next-page"


def test_collect_sans_cle_retourne_vide(monkeypatch):
    monkeypatch.setattr(mediacloud.config, "MEDIACLOUD_API_KEY", "")
    assert mediacloud.collect() == []


def test_collect_respecte_plafond_et_deduplique():
    class DuplicateClient:
        def story_list(self, query, **kwargs):
            story = {"title": "Titre", "url": "https://example.fr/a"}
            return [story, story], None

    assert len(mediacloud.collect(
        client=DuplicateClient(), api_key="", max_articles=1
    )) == 1
