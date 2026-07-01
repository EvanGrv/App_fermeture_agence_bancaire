# tests/test_pipeline.py
import backend.store as store
from backend import pipeline, prefilter, context_builder
from backend.extraction_cache import content_hash
import config

def _compact_hash(art):
    """Compute the content hash as the pipeline does: after prefilter + compact context."""
    pf = prefilter.analyse(art)
    pf.compact_context = context_builder.build_compact_context(art, pf)
    art_ia = dict(art)
    art_ia["texte"] = pf.compact_context
    return content_hash(art_ia)


def _article(url, pertinent=True):
    if pertinent:
        return {"titre": "BNP ferme son agence", "texte": "agence fermée à Lyon",
                "url": url, "date": "2026-01-10", "source": "GN", "departement": "69"}
    return {"titre": "Météo", "texte": "soleil", "url": url, "date": "", "source": "GN",
            "departement": None}

def _extractor(article):
    return {"id": "abc123", "banque": "BNP", "commune": "Lyon", "code_insee": None,
            "departement": "69", "type": "fermeture", "date_annonce": "2026-01-10",
            "date_fermeture": None, "statut": "projet", "fiabilite": 3,
            "lat": None, "lon": None, "citation": "agence fermée à Lyon"}

def _geo(commune, dept):
    return {"lat": 45.76, "lon": 4.85, "code_insee": "69123", "departement": "69"}

def test_pipeline_complet(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    collectors = [lambda: [_article("http://1"), _article("http://2", pertinent=False)]]
    recap = pipeline.run_pipeline(
        conn, collectors,
        extractor_fn=_extractor,
        geocoder_fn=_geo,
    )
    assert recap["articles"] == 2
    assert recap["filtres"] == 1   # seul l'article pertinent passe le pré-filtre
    assert recap["extraits"] == 1
    assert recap["fermetures"] == 1
    row = conn.execute("SELECT lat, lon FROM closures WHERE id='abc123'").fetchone()
    assert row == (45.76, 4.85)

def test_pipeline_enrichit_departement_si_absent(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    def extractor_sans_dept(article):
        r = _extractor(article); r["departement"] = None; r["code_insee"] = None
        return r
    collectors = [lambda: [_article("http://1")]]
    pipeline.run_pipeline(conn, collectors, extractor_sans_dept, _geo)
    row = conn.execute("SELECT departement, code_insee FROM closures WHERE id='abc123'").fetchone()
    assert row == ("69", "69123")

def test_ingest_closures_geocode_adresse(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    closures = [{
        "id": "sg0000000000001", "banque": "Société Générale", "commune": "Bernin",
        "code_insee": None, "departement": "38", "type": "fermeture",
        "date_annonce": None, "date_fermeture": "2026-07-16", "statut": "confirmé",
        "fiabilite": 5, "lat": None, "lon": None, "citation": "transfère ses activités",
        "_adresse": "ZAC Les Michellières, 38190 Bernin",
        "_source_url": "https://agences.sg.fr/",
    }]
    n = pipeline.ingest_closures(
        conn, closures,
        lambda adr: {"lat": 45.27, "lon": 5.86, "code_insee": "38045", "departement": "38"},
    )
    assert n == 1
    row = conn.execute("SELECT lat, lon, code_insee FROM closures WHERE id='sg0000000000001'").fetchone()
    assert row == (45.27, 5.86, "38045")
    src = conn.execute("SELECT source FROM sources WHERE closure_id='sg0000000000001'").fetchone()
    assert src[0] == "SG (localisateur officiel)"

def test_pipeline_idempotent(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    collectors = [lambda: [_article("http://1")]]
    pipeline.run_pipeline(conn, collectors, _extractor, _geo)
    recap = pipeline.run_pipeline(conn, collectors, _extractor, _geo)
    assert recap["filtres"] == 0  # URL déjà vue -> ignorée
    n = conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0]
    assert n == 1

def test_pipeline_stocke_vigilance_si_extraction_non_publiable(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    collectors = [lambda: [_article("http://v")]]
    vus = []

    def vigilance_fn(article, raison):
        vus.append((article["url"], raison))
        return "v1"

    recap = pipeline.run_pipeline(
        conn,
        collectors,
        extractor_fn=lambda art: None,
        geocoder_fn=_geo,
        vigilance_fn=vigilance_fn,
    )
    assert recap["vigilances"] == 1
    assert vus == [("http://v", "article pertinent sans fermeture publiable")]

def test_pipeline_rejette_commune_inconnue_ou_non_nominative(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    collectors = [lambda: [{
        "titre": "Une grande première: suppressions de postes et fermetures d'agences",
        "texte": "Les salariés du Crédit Agricole sont appelés à la grève, sans commune d'agence citée.",
        "url": "http://bfmtv-test",
        "date": "2026-01-13",
        "source": "Google News",
        "departement": None,
    }]]
    vus = []

    def extractor(_article):
        result = _extractor(_article)
        result["commune"] = "inconnu"
        result["departement"] = None
        return result

    def vigilance_fn(article, raison):
        vus.append((article["url"], raison))
        return "v1"

    recap = pipeline.run_pipeline(
        conn,
        collectors,
        extractor_fn=extractor,
        geocoder_fn=lambda commune, dept: None,
        vigilance_fn=vigilance_fn,
    )

    assert recap["fermetures"] == 0
    assert recap["rejets_validation"] == 1
    assert recap["vigilances"] == 1
    assert "commune" in vus[0][1]
    assert conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0] == 0

def test_pipeline_rejette_territoire_pris_pour_commune(tmp_path):
    conn = store.init_db(tmp_path / "t.db")

    def extractor(_article):
        result = _extractor(_article)
        result["commune"] = "Franche-Comté"
        result["departement"] = None
        return result

    recap = pipeline.run_pipeline(
        conn,
        [lambda: [_article("http://franche-comte")]],
        extractor_fn=extractor,
        geocoder_fn=lambda commune, dept: {"lat": 47.0, "lon": 6.0, "code_insee": "25000", "departement": "25"},
    )

    assert recap["fermetures"] == 0
    assert recap["rejets_validation"] == 1


def test_article_court_est_enrichi_avant_extraction(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    # Article court (< 400 chars) qui passe le préfiltre
    article_court = {
        "titre": "Crédit Agricole ferme son agence",
        "texte": "ferme",  # très court, < 400 chars
        "url": "http://exemple.com/article-credit-agricole",
        "date": "2026-01-10",
        "source": "GN",
        "departement": None,
    }
    arts_recus = []

    def extractor_espion(art):
        arts_recus.append(dict(art))
        return None  # pas de fermeture, on teste juste l'enrichissement

    enrich_fn = lambda url: "AGENCE DE TestCommune, détails supplémentaires sur la fermeture."

    pipeline.run_pipeline(
        conn,
        [lambda: [article_court]],
        extractor_fn=extractor_espion,
        geocoder_fn=lambda commune, dept: None,
        enrich_fn=enrich_fn,
        since_date=None,
    )

    assert len(arts_recus) == 1, "L'extracteur doit avoir été appelé une fois"
    assert "AGENCE DE TestCommune" in arts_recus[0]["texte"], \
        "Le texte enrichi doit contenir le sentinel de l'enrich_fn"


def test_fulltext_systematique_enrichit_meme_les_articles_longs(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    texte_long = "Crédit Agricole ferme son agence. " * 15  # > 400 chars
    article_long = {
        "titre": "Crédit Agricole ferme son agence", "texte": texte_long,
        "url": "http://exemple.com/article-long", "date": "2026-01-10",
        "source": "GN", "departement": None,
    }
    enrich_appels = []

    def enrich_espion(url):
        enrich_appels.append(url)
        return "texte additionnel"

    pipeline.run_pipeline(
        conn, [lambda: [article_long]],
        extractor_fn=lambda art: None,
        geocoder_fn=lambda commune, dept: None,
        enrich_fn=enrich_espion, since_date=None,
    )
    assert len(enrich_appels) == 1, "fulltext systématique : l'article long est aussi enrichi"


def test_pipeline_extraction_cachee_pas_de_2e_appel_ia(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    appels = []

    def extractor_compteur(art):
        appels.append(art["url"])
        return None  # 'none' doit être caché

    collectors = [lambda: [_article("http://cache-ia")]]
    pipeline.run_pipeline(conn, collectors, extractor_compteur, _geo,
                          enrich_fn=lambda u: "")
    # On efface seen_urls pour forcer le 2e passage jusqu'à l'extraction
    conn.execute("DELETE FROM seen_urls"); conn.commit()
    pipeline.run_pipeline(conn, collectors, extractor_compteur, _geo,
                          enrich_fn=lambda u: "")
    assert len(appels) == 1, "le cache d'extraction évite le 2e appel IA"


def test_pipeline_score_bas_route_vigilance_sans_ia(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    # Article RH/social sans "agence" mais avec banque+terme (passe is_relevant),
    # score <= PREFILTER_MIN_SCORE -> pas d'IA, vigilance.
    art = {"titre": "Plan social à la Société Générale",
           "texte": "Suppression de postes, licenciements et grève des salariés.",
           "url": "http://rh", "date": "2026-01-10", "source": "GN", "departement": None}
    appels_ia = []
    vus = []

    def extractor_espion(a):
        appels_ia.append(a["url"])
        return None

    def vigilance_fn(a, raison):
        vus.append(raison)
        return "v1"

    pipeline.run_pipeline(conn, [lambda: [art]], extractor_espion,
                          lambda c, d: None, vigilance_fn=vigilance_fn,
                          enrich_fn=lambda u: "")
    assert appels_ia == [], "score bas -> aucun appel IA"
    assert vus and "score" in vus[0]


def test_pipeline_envoie_contexte_compact_a_l_ia(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    art = {"titre": "Société Générale ferme son agence de Rennes",
           "texte": "L'agence de Rennes fermera le 30 juin 2026.",
           "url": "http://ok", "date": "2026-01-10", "source": "GN", "departement": "35"}
    recu = []

    def extractor_espion(a):
        recu.append(a["texte"])
        return None

    pipeline.run_pipeline(conn, [lambda: [art]], extractor_espion,
                          lambda c, d: None, enrich_fn=lambda u: "")
    assert len(recu) == 1
    assert recu[0].startswith("TITRE:")  # contexte compact, pas le texte brut
    assert "Rennes" in recu[0]


def test_pipeline_ne_marque_pas_seen_apres_erreur_ia_retryable(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    appels = []
    url = "http://retry-ia"

    def extractor_retry(art):
        appels.append(art["url"])
        if len(appels) == 1:
            raise RuntimeError("API 529")
        return None

    collectors = [lambda: [_article(url)]]
    pipeline.run_pipeline(conn, collectors, extractor_retry, _geo, enrich_fn=lambda u: "")
    assert len(appels) == 1
    assert not store.is_url_seen(conn, url), "une erreur IA réessayable ne doit pas marquer l'URL seen"
    row = store.get_extraction(conn, _compact_hash(_article(url)), config.EXTRACTION_VERSION,
                               config.ANTHROPIC_MODEL)
    assert row["status"] == "error"

    row["retry_after"] = "2000-01-01T00:00:00+00:00"
    store.upsert_extraction(conn, row)
    pipeline.run_pipeline(conn, collectors, extractor_retry, _geo, enrich_fn=lambda u: "")
    assert len(appels) == 2
    assert store.is_url_seen(conn, url), "après extraction réussie en none, l'URL peut être marquée seen"
