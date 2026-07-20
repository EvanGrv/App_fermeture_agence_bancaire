from datetime import date
from pathlib import Path
import urllib.parse
import config
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


def test_queries_couvrent_domaines_pqr_de_la_reference():
    """Les domaines observés dans l'Excel de référence sont ciblés en site:."""
    requetes = " ".join(google_news.QUERIES)
    for domaine in ("dna.fr", "info-chalon.com", "deltafm.fr",
                    "europesays.com", "bienpublic.com"):
        assert f"site:{domaine} fermeture agence bancaire" in requetes


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

def test_queries_contiennent_requetes_euphemismes():
    requetes = google_news.QUERIES
    assert "banque cesse son activité agence" in requetes
    assert "agence bancaire transférée" in requetes
    assert "réorganisation réseau bancaire agence" in requetes


def test_queries_ciblent_banque_postale_bureaux_et_previsions():
    requetes = " ".join(google_news.QUERIES)
    assert '"La Banque Postale" "bureau de poste" "fermeture"' in requetes
    assert '"La Banque Postale" "services financiers" "fermeture"' in requetes
    assert '"La Banque Postale" "fermera"' in requetes
    assert "La Banque Postale fermeture agence Normandie" in requetes
    assert any("La Banque Postale" in q for q in google_news._DENSE)


def test_queries_ciblent_fermetures_bureaux_de_poste():
    requetes = " ".join(google_news.QUERIES)
    assert '"fermeture du bureau de poste"' in requetes
    assert '"bureau de poste" "va fermer"' in requetes
    assert "fermeture bureau de poste Indre" in requetes
    assert any("bureau de poste" in q for q in google_news._DENSE)


# ---------------------------------------------------------------------------
# Tests Task 12: découpage mensuel des requêtes denses
# ---------------------------------------------------------------------------

def test_parse_when_to_start_days():
    today = date(2026, 6, 25)
    result = google_news._parse_when_to_start("30d", today)
    assert result == date(2026, 5, 26)


def test_parse_when_to_start_year():
    today = date(2026, 6, 25)
    result = google_news._parse_when_to_start("1y", today)
    assert result == date(2025, 6, 25)  # today - 365 days


def test_parse_when_to_start_hours():
    today = date(2026, 6, 25)
    result = google_news._parse_when_to_start("24h", today)
    assert result == today  # same day


def test_parse_when_to_start_invalid():
    today = date(2026, 6, 25)
    assert google_news._parse_when_to_start("", today) is None
    assert google_news._parse_when_to_start("abc", today) is None
    assert google_news._parse_when_to_start("3m", today) is None


def test_month_ranges_tile_span():
    start = date(2025, 11, 15)
    end = date(2026, 2, 10)
    buckets = google_news._month_ranges(start, end)
    # Should have 4 buckets: Nov15-Dec1, Dec1-Jan1, Jan1-Feb1, Feb1-Feb11
    assert len(buckets) == 4
    # First bucket starts at start date
    assert buckets[0][0] == "2025-11-15"
    # Last bucket ends at end + 1 day
    assert buckets[-1][1] == "2026-02-11"
    # Contiguous: each before == next after
    for i in range(len(buckets) - 1):
        assert buckets[i][1] == buckets[i + 1][0], (
            f"Gap between bucket {i} and {i+1}: {buckets[i][1]} != {buckets[i+1][0]}"
        )


def test_month_ranges_single_month():
    # Start and end in same month: just one bucket
    start = date(2026, 1, 5)
    end = date(2026, 1, 20)
    buckets = google_news._month_ranges(start, end)
    assert len(buckets) == 1
    assert buckets[0][0] == "2026-01-05"
    assert buckets[0][1] == "2026-01-21"


def test_feed_url_after_before():
    url = google_news._feed_url("ma requête", after="2025-01-01", before="2025-02-01")
    decoded = urllib.parse.unquote(url)
    assert "after:2025-01-01" in decoded
    assert "before:2025-02-01" in decoded
    assert "when:" not in decoded


def test_feed_url_default_uses_when(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_NEWS_WHEN", "30d")
    url = google_news._feed_url("ma requête")
    decoded = urllib.parse.unquote(url)
    assert "when:30d" in decoded
    assert "after:" not in decoded


def test_collect_slices_dense_query(monkeypatch):
    """A dense query with a multi-month window must call fetch once per month bucket."""
    xml = FIXT.read_text(encoding="utf-8")
    call_count = []

    def spy_fetch(url):
        call_count.append(url)
        return xml

    # 90d window → ~3 months → expect >1 fetch call per dense query
    monkeypatch.setattr(config, "GOOGLE_NEWS_WHEN", "90d")
    # Pick the first thematic query (guaranteed dense)
    dense_query = google_news._THEMATIQUES[0]
    google_news.collect(fetch=spy_fetch, queries=[dense_query])

    today = date.today()
    start = google_news._parse_when_to_start("90d", today)
    expected_buckets = google_news._month_ranges(start, today)
    assert len(call_count) == len(expected_buckets)
    assert len(call_count) > 1


def test_collect_single_for_longtail(monkeypatch):
    """A non-dense (long-tail) query must call fetch exactly once."""
    xml = FIXT.read_text(encoding="utf-8")
    call_count = []

    def spy_fetch(url):
        call_count.append(url)
        return xml

    monkeypatch.setattr(config, "GOOGLE_NEWS_WHEN", "90d")
    # A department query is not dense
    longtail_query = google_news._PAR_DEPARTEMENT[0]
    google_news.collect(fetch=spy_fetch, queries=[longtail_query])
    assert len(call_count) == 1


def test_collect_decoupe_requete_explicitement_forcee(monkeypatch):
    xml = FIXT.read_text(encoding="utf-8")
    calls = []
    query = '"bureau de poste" "transformé en relais poste"'
    monkeypatch.setattr(config, "GOOGLE_NEWS_WHEN", "90d")
    google_news.collect(
        fetch=lambda url: calls.append(url) or xml,
        queries=[query], slice_queries={query},
    )
    assert len(calls) == len(google_news._month_ranges(
        google_news._parse_when_to_start("90d", date.today()), date.today()
    ))


def test_dense_set_contains_thematiques_and_big_banks():
    """_DENSE must contain all thematic queries and the big-bank national queries."""
    for q in google_news._THEMATIQUES:
        assert q in google_news._DENSE, f"Thematic query not in _DENSE: {q}"
    # Big national bank queries for the three high-volume banks
    assert any("Crédit Agricole" in q and "fermeture agence" in q and len(q.split()) <= 4
               for q in google_news._DENSE)
    assert any("Société Générale" in q and "fermeture agence" in q and len(q.split()) <= 4
               for q in google_news._DENSE)
    assert any("BNP" in q and "fermeture agence" in q and len(q.split()) <= 4
               for q in google_news._DENSE)
    assert any("La Banque Postale" in q and "fermeture agence" in q
               for q in google_news._DENSE)
