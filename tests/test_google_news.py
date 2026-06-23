from pathlib import Path
from backend.collectors import google_news

FIXT = Path(__file__).parent / "fixtures" / "google_news_sample.xml"

def test_build_query_contient_departement():
    q = google_news.build_query("Ille-et-Vilaine")
    assert "Ille-et-Vilaine" in q

def test_parse_feed():
    arts = google_news.parse_feed(FIXT.read_text(encoding="utf-8"))
    assert len(arts) == 2
    a = arts[0]
    assert a["titre"].startswith("La Société Générale")
    assert a["url"] == "https://exemple.fr/article-1"
    assert a["source"] == "Google News"
    assert set(a) >= {"titre", "texte", "url", "date", "source", "departement"}

def test_collect_injecte_fetch():
    xml = FIXT.read_text(encoding="utf-8")
    arts = google_news.collect(fetch=lambda url: xml)
    # 2 articles par département × nb départements
    assert len(arts) == 2 * len(__import__("config").DEPARTEMENTS)
    assert all(a["departement"] is not None for a in arts)
