from datetime import date
from io import BytesIO

from backend.collectors import common_crawl
from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter


def _collections():
    return [
        {"id": "CC-MAIN-2026-20", "to": "20260520000000"},
        {"id": "CC-MAIN-2026-10", "to": "20260310000000"},
        {"id": "CC-MAIN-2025-40", "to": "20251010000000"},
        {"id": "CC-MAIN-2025-20", "to": "20250520000000"},
        {"id": "CC-MAIN-2024-10", "to": "20240310000000"},
    ]


def test_select_indexes_repartit_sur_toute_la_fenetre():
    selected = common_crawl.select_indexes(
        _collections(), "2025-01-01", 3, date(2026, 6, 1)
    )
    assert selected == [
        "CC-MAIN-2026-20",
        "CC-MAIN-2025-40",
        "CC-MAIN-2025-20",
    ]


def test_select_indexes_accepte_les_dates_iso_actuelles():
    selected = common_crawl.select_indexes(
        [{
            "id": "CC-MAIN-2026-25",
            "from": "2026-06-05T21:48:11",
            "to": "2026-06-18T19:32:05",
        }],
        "2025-01-01",
        2,
        date(2026, 7, 22),
    )
    assert selected == ["CC-MAIN-2026-25"]


def test_select_domains_tourne_par_semaine():
    domains = ["a.fr", "b.fr", "c.fr", "d.fr", "e.fr"]
    first = common_crawl.select_domains(domains, 2, date(2026, 1, 5))
    second = common_crawl.select_domains(domains, 2, date(2026, 1, 12))
    assert len(first) == 2
    assert len(second) == 2
    assert first != second


def test_is_deep_run_exige_environ_24_mois(monkeypatch):
    monkeypatch.setattr(common_crawl.config, "COMMON_CRAWL_MIN_DAYS", 700)
    today = date(2026, 7, 22)
    assert common_crawl.is_deep_run("2024-07-22", today)
    assert not common_crawl.is_deep_run("2026-05-22", today)


def test_record_to_article_extrait_et_prefiltre(monkeypatch):
    raw = b"""<html><head><title>Une agence bancaire va fermer</title></head>
    <body><article>Le Credit Agricole annonce la fermeture de son agence bancaire
    de Tours au 1er septembre 2026.</article></body></html>"""
    monkeypatch.setattr(common_crawl, "extract_warc_payload", lambda blob: raw)
    article = common_crawl.record_to_article({
        "url": "https://journal.fr/banque-fermeture-tours",
        "timestamp": "20260615120000",
        "encoding": "UTF-8",
    }, b"warc")
    assert article is not None
    assert article["titre"] == "Une agence bancaire va fermer"
    assert article["date"] == "2026-06-15"
    assert article["canal"] == "common_crawl"


def test_extract_warc_payload_lit_un_vrai_record_gzip():
    output = BytesIO()
    writer = WARCWriter(output, gzip=True)
    body = b"<html><body>fermeture agence bancaire</body></html>"
    http_headers = StatusAndHeaders(
        "200 OK", [("Content-Type", "text/html")], protocol="HTTP/1.1"
    )
    record = writer.create_warc_record(
        "https://example.fr/fermeture",
        "response",
        payload=BytesIO(body),
        http_headers=http_headers,
    )
    writer.write_record(record)

    assert common_crawl.extract_warc_payload(output.getvalue()) == body


def test_collect_agrege_crawls_et_deduplique(monkeypatch):
    monkeypatch.setattr(common_crawl.config, "COMMON_CRAWL_MIN_DAYS", 10)
    index_calls = []

    def index_fetch(index_id, domain, limit):
        index_calls.append((index_id, domain, limit))
        return [{
            "url": f"https://{domain}/fermeture-agence",
            "timestamp": "20260615120000",
            "filename": "crawl/file.warc.gz",
            "offset": "0",
            "length": "100",
        }]

    monkeypatch.setattr(common_crawl, "record_to_article", lambda record, blob: {
        "titre": "Fermeture",
        "texte": "Une agence bancaire ferme.",
        "url": record["url"],
        "date": "2026-06-15",
        "source": "journal.fr",
        "departement": None,
        "canal": "common_crawl",
    })
    articles = common_crawl.collect(
        since_date="2025-01-01",
        today=date(2026, 7, 22),
        domains=["journal.fr"],
        collinfo_fetch=_collections,
        index_fetch=index_fetch,
        record_fetch=lambda record: b"warc",
        max_domains=1,
        max_indexes=2,
        records_per_domain=4,
        max_articles=10,
    )
    assert len(index_calls) == 2
    assert len(articles) == 1


def test_collect_court_ne_touche_pas_le_reseau(monkeypatch):
    monkeypatch.setattr(common_crawl.config, "COMMON_CRAWL_MIN_DAYS", 700)
    assert common_crawl.collect(
        since_date="2026-06-01",
        today=date(2026, 7, 22),
        collinfo_fetch=lambda: (_ for _ in ()).throw(AssertionError()),
    ) == []


def test_index_fetch_emploie_filtres_cdx_officiels(monkeypatch):
    captured = {}
    monkeypatch.setattr(common_crawl.config, "COMMON_CRAWL_THROTTLE_SECONDS", 0)

    class Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        captured.update(kwargs["params"])
        return Response()

    monkeypatch.setattr(common_crawl.requests, "get", fake_get)
    assert common_crawl._default_index_fetch(
        "CC-MAIN-2026-25", "journal.fr", 5
    ) == []
    assert captured["filter"][0] == "=status:200"
    assert captured["filter"][1] == "=mime:text/html"
    assert captured["filter"][2].startswith("~url:")
    assert captured["filter"][3].startswith("~url:")


def test_index_fetch_reessaie_une_erreur_503(monkeypatch):
    calls = []
    monkeypatch.setattr(common_crawl.config, "COMMON_CRAWL_THROTTLE_SECONDS", 0)
    monkeypatch.setattr(common_crawl.config, "COMMON_CRAWL_RETRIES", 1)
    monkeypatch.setattr(common_crawl.config, "COMMON_CRAWL_RETRY_BASE_SECONDS", 0)

    class Response:
        text = ""
        headers = {}

        def __init__(self, status_code):
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    def fake_get(url, **kwargs):
        calls.append(url)
        return Response(503 if len(calls) == 1 else 200)

    monkeypatch.setattr(common_crawl.requests, "get", fake_get)
    assert common_crawl._default_index_fetch(
        "CC-MAIN-2026-25", "journal.fr", 5
    ) == []
    assert len(calls) == 2
