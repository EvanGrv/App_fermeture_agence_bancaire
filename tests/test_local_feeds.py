from pathlib import Path
from backend.collectors import local_feeds

FIXT = Path(__file__).parent / "fixtures" / "google_news_sample.xml"


def test_parse_feed_source_directe():
    arts = local_feeds.parse_feed(FIXT.read_text(encoding="utf-8"), "Ouest-France")

    assert len(arts) == 2
    assert arts[0]["source"] == "Ouest-France"
    assert arts[0]["url"] == "https://exemple.fr/article-1"
    assert set(arts[0]) >= {"titre", "texte", "url", "date", "source", "departement"}


def test_collect_dedupe_multi_flux():
    xml = FIXT.read_text(encoding="utf-8")
    feeds = [
        {"label": "Actu.fr", "url": "https://actu.fr/rss.xml"},
        {"label": "Ouest-France", "url": "https://www.ouest-france.fr/rss/france"},
    ]

    arts = local_feeds.collect(fetch=lambda url: xml, feeds=feeds)

    assert len(arts) == 2


def test_collect_continue_si_flux_en_erreur():
    xml = FIXT.read_text(encoding="utf-8")
    feeds = [
        {"label": "Cassé", "url": "https://exemple.invalid/rss.xml"},
        {"label": "Ici", "url": "https://www.ici.fr/rss/infos.xml"},
    ]

    def fetch(url):
        if "invalid" in url:
            raise RuntimeError("boom")
        return xml

    arts = local_feeds.collect(fetch=fetch, feeds=feeds)

    assert len(arts) == 2
    assert {a["source"] for a in arts} == {"Ici"}
