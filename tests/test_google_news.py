from pathlib import Path
from backend.collectors import google_news

FIXT = Path(__file__).parent / "fixtures" / "google_news_sample.xml"


def test_feed_url_contient_query():
    url = google_news._feed_url("fermeture agence bancaire")
    assert "news.google.com/rss/search" in url
    assert "fermeture" in url


def test_queries_non_vide():
    assert len(google_news.QUERIES) >= 3

def test_queries_contient_variantes_regionales():
    requetes = " ".join(google_news.QUERIES)
    assert "Crédit Agricole Loire Haute-Loire fermeture agence" in requetes
    assert "SG SMC fermeture agence" in requetes
    assert "BPGO fermeture agence" in requetes
    assert "CEBPL fermeture agence" in requetes

def test_queries_couvrent_regions_departements_et_presse_regionale():
    requetes = " ".join(google_news.QUERIES)
    assert "fermeture agence bancaire Normandie" in requetes
    assert "Crédit Agricole fermeture agence Bourgogne-Franche-Comté" in requetes
    assert "fermeture agence bancaire Indre" in requetes
    assert "site:ouest-france.fr fermeture agence bancaire" in requetes
    assert "site:actu.fr fermeture agence bancaire" in requetes


def test_parse_feed():
    arts = google_news.parse_feed(FIXT.read_text(encoding="utf-8"))
    assert len(arts) == 2
    a = arts[0]
    assert a["titre"].startswith("La Société Générale")
    assert a["url"] == "https://exemple.fr/article-1"
    assert a["source"] == "Google News"
    assert set(a) >= {"titre", "texte", "url", "date", "source", "departement"}


def test_collect_injecte_fetch_dedupe():
    xml = FIXT.read_text(encoding="utf-8")
    # Toutes les requêtes renvoient le même flux => dédup par URL => 2 uniques.
    arts = google_news.collect(fetch=lambda url: xml)
    assert len(arts) == 2
    assert all(a["departement"] is None for a in arts)
