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
    return {
        "article_type": "single_closure",
        "closures": [{
            "bank": "BNP", "agency_label": "", "commune": "Lyon",
            "departement": "69", "region": None, "address": "",
            "closure_date": None, "date_precision": "unknown",
            "status": "announced", "closure_type": "closure",
            "is_physical_agency": True, "confidence": 0.6,
            "evidence": "agence fermée à Lyon",
        }],
        "department_signals": [], "vague_signals": [], "confidence": 0.6,
        "needs_sonnet": False, "reason": "",
    }

def _structured(**closure_over):
    result = _extractor({})
    result["closures"][0].update(closure_over)
    return result

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
    row = conn.execute("SELECT lat, lon FROM closures WHERE commune='Lyon'").fetchone()
    assert row == (45.76, 4.85)

def test_pipeline_enrichit_departement_si_absent(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    def extractor_sans_dept(article):
        r = _extractor(article); r["closures"][0]["departement"] = None
        return r
    collectors = [lambda: [_article("http://1")]]
    pipeline.run_pipeline(conn, collectors, extractor_sans_dept, _geo)
    row = conn.execute("SELECT departement, code_insee FROM closures WHERE commune='Lyon'").fetchone()
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


def test_pipeline_publie_titre_postal_explicite_sans_appel_ia(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    article = {
        "titre": "Orléans : le bureau de poste fermera définitivement le 31 octobre",
        "texte": "",
        "url": "http://postal-orleans",
        "date": "2024-09-03",
        "source": "PQR",
        "departement": "45",
    }
    appels_ia = []

    def extractor_spy(art):
        appels_ia.append(art)
        return None

    def geocode(commune, departement=None):
        if commune == "Orléans":
            return {
                "commune": "Orléans", "lat": 47.9, "lon": 1.9,
                "code_insee": "45234", "departement": "45",
            }
        return None

    recap = pipeline.run_pipeline(
        conn,
        [lambda: [article]],
        extractor_spy,
        geocode,
        since_date="2024-07-20",
        enrich_fn=lambda url: "",
    )
    assert appels_ia == []
    assert recap["fermetures"] == 1
    row = conn.execute(
        "SELECT banque, date_fermeture, service_impact FROM closures"
    ).fetchone()
    assert row == ("La Banque Postale", "2024-10-31", "fermeture_lbp_complete")
    assert store.is_url_seen(conn, article["url"])


def test_backlog_postal_resout_vigilance_existante_sans_ia(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    url = "http://postal-marnay"
    store.upsert_vigilance(conn, {
        "id": "marnay",
        "banque": "La Banque Postale",
        "departement": "70",
        "titre": "Marnay : fermé définitivement, le bureau de poste ne rouvrira pas",
        "extrait": "",
        "url": url,
        "source": "PQR",
        "date": "2025-05-15",
        "score": 5,
        "raison": "article pertinent sans fermeture publiable",
    })

    def geocode(commune, departement=None):
        if commune == "Marnay":
            return {
                "commune": "Marnay", "lat": 47.3, "lon": 5.8,
                "code_insee": "70334", "departement": "70",
            }
        return None

    recap = pipeline.ingest_postal_vigilance_backlog(
        conn,
        store.list_postal_vigilance_articles(conn),
        geocode,
        since_date="2024-07-20",
    )
    assert recap["fermetures"] == 1
    assert store.is_url_seen(conn, url)
    assert conn.execute("SELECT COUNT(*) FROM vigilances").fetchone()[0] == 0

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
        return _structured(commune="inconnu", departement=None)

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
        return _structured(commune="Franche-Comté", departement=None)

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
    assert store.is_url_seen(conn, "http://rh"), "l'URL skippée doit être marquée seen"


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
    row = store.get_extraction(
        conn,
        _compact_hash(_article(url)),
        config.EXTRACTION_VERSION,
        config.EXTRACTION_CACHE_MODEL,
    )
    assert row["status"] == "error"

    row["retry_after"] = "2000-01-01T00:00:00+00:00"
    store.upsert_extraction(conn, row)
    pipeline.run_pipeline(conn, collectors, extractor_retry, _geo, enrich_fn=lambda u: "")
    assert len(appels) == 2
    assert store.is_url_seen(conn, url), "après extraction réussie en none, l'URL peut être marquée seen"


def test_pipeline_list_closures_explose_en_n_fermetures(tmp_path):
    conn = store.init_db(tmp_path / "t.db")

    def extractor(_a):
        base = _extractor(_a)["closures"][0]

        def item(commune):
            c = dict(base)
            c["commune"] = commune
            c["departement"] = "19"
            return c

        return {
            "article_type": "list_closures",
            "closures": [item("Bessines"), item("Tulle"), item("Guéret")],
            "department_signals": [], "vague_signals": [], "confidence": 0.6,
            "needs_sonnet": False, "reason": "",
        }

    geo = lambda commune, dept: {
        "lat": 45.0, "lon": 2.0, "code_insee": "00000", "departement": "19",
    }
    article = {
        "titre": "BNP Paribas ferme trois agences à Bessines, Tulle et Guéret",
        "texte": "Les agences BNP de Bessines, Tulle et Guéret vont fermer.",
        "url": "http://list", "date": "2026-01-10", "source": "GN",
        "departement": "19",
    }
    recap = pipeline.run_pipeline(
        conn, [lambda: [article]], extractor, geo,
        enrich_fn=lambda u: "",
    )
    assert recap["fermetures"] == 3
    assert conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0] == 3


def test_pipeline_department_signal_route_vigilance(tmp_path):
    conn = store.init_db(tmp_path / "t.db")

    def extractor(_a):
        return {
            "article_type": "department_signal",
            "closures": [],
            "department_signals": [{
                "bank": "BNP", "departement": "18", "count": 10,
                "communes_mentioned": ["Bourges"], "confidence": 0.6,
                "evidence": "10 agences dans le Cher",
            }],
            "vague_signals": [], "confidence": 0.6,
            "needs_sonnet": False, "reason": "",
        }

    recap = pipeline.run_pipeline(
        conn, [lambda: [_article("http://dep")]], extractor, _geo,
        enrich_fn=lambda u: "",
    )
    assert recap["fermetures"] == 0
    assert conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM vigilances").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM department_signals").fetchone()[0] == 1


def test_pipeline_non_geocode_stocke_closure_unlocated(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    vus = []

    def vigilance_fn(article, raison):
        vus.append(raison)
        return "v1"

    recap = pipeline.run_pipeline(
        conn, [lambda: [_article("http://nogeo")]], _extractor,
        geocoder_fn=lambda commune, dept: None,
        vigilance_fn=vigilance_fn,
        enrich_fn=lambda u: "",
    )

    assert recap["fermetures"] == 0
    assert recap["rejets_validation"] == 1
    assert recap["vigilances"] == 1
    row = conn.execute(
        "SELECT banque, commune, raison FROM closures_unlocated WHERE url='http://nogeo'"
    ).fetchone()
    assert row[0] == "BNP Paribas"
    assert row[1] == "Lyon"
    assert "commune non géocodée" in row[2]


def test_pipeline_rejette_sortie_lbp_incompatible_avec_article_source(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    article = {
        "titre": "Le bureau de poste ferme en août, ce maire de Lozère proteste",
        "texte": "La fermeture du bureau de poste est confirmée.",
        "url": "http://lbp-lozere", "date": "2026-06-17",
        "source": "PQR", "departement": None,
    }

    def extractor(_article):
        return _structured(
            bank="La Banque Postale", commune="Plélan-le-Grand",
            departement="35", status="confirmed",
            closure_date="2026-08-01", date_precision="approximate",
            evidence="Le bureau de poste ferme en août",
        )

    recap = pipeline.run_pipeline(
        conn, [lambda: [article]], extractor,
        lambda commune, dept: {
            "commune": commune, "lat": 48.0, "lon": -2.0,
            "code_insee": "35223", "departement": "35",
        },
        enrich_fn=lambda _url: "",
    )

    assert recap["fermetures"] == 0
    assert recap["rejets_validation"] == 1
    assert conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0] == 0
    reason = conn.execute("SELECT raison FROM closures_unlocated").fetchone()[0]
    assert "département source 48" in reason


def test_pipeline_persiste_json_riche(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    pipeline.run_pipeline(
        conn, [lambda: [_article("http://rich")]], _extractor, _geo,
        enrich_fn=lambda u: "",
    )
    row = conn.execute("SELECT result_json FROM extractions").fetchone()
    assert row is not None and "article_type" in row[0]
