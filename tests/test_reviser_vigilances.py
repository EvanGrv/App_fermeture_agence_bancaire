import backend.store as store
from backend import vigilance_review as vr


def _geocode(commune, departement=None):
    if vr._cle(commune) == vr._cle("Bar-le-Duc"):
        return {"lat": 48.7, "lon": 5.16, "code_insee": "55029",
                "departement": "55", "commune": "Bar-le-Duc"}
    return None


def _seed_vigilance(conn):
    store.upsert_vigilance(conn, dict(
        id="v1", banque="BNP Paribas", departement="55",
        titre="La BNP Paribas de Bar-le-Duc va fermer",
        extrait="Les clients s'inquiètent.", url="http://v/1",
        source="L'Est Républicain", date="2026-01-01", score=4, raison="r"))


def _article():
    return {
        "titre": "BNP Paribas ferme son agence de Bar-le-Duc",
        "texte": "Fermeture prévue le 31 mars 2026.",
        "url": "https://estrepublicain.fr/bar-le-duc-bnp",
        "date": "2026-01-10", "source": "L'Est Républicain",
    }


def _extractor(art):
    return {
        "id": "c1", "banque": "BNP Paribas", "commune": "Bar-le-Duc",
        "code_insee": None, "departement": "55", "type": "fermeture",
        "date_annonce": art.get("date"), "date_fermeture": "2026-03-31",
        "statut": "confirmé", "statut_temporel": "a_venir",
        "date_fermeture_approx": 0, "fiabilite": 4,
        "lat": None, "lon": None, "citation": "ferme",
    }


def test_reviser_cree_fermeture_et_enregistre_review(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    _seed_vigilance(conn)

    summary = vr.reviser_vigilances(
        conn,
        search_fn=lambda q, since=None, limit=10: [_article()],
        extractor_fn=_extractor,
        geocode_fn=_geocode,
    )
    assert summary["reviewed"] == 1
    assert summary["closures_created"] == 1
    # fermeture persistée + source rattachée
    assert conn.execute("SELECT COUNT(*) FROM closures WHERE id='c1'").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM sources WHERE closure_id='c1'").fetchone()[0] == 1
    # review enregistrée
    row = conn.execute(
        "SELECT closures_created FROM vigilance_reviews WHERE id='v1'").fetchone()
    assert row == (1,)


def test_reviser_ne_retraite_pas_si_recent(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    _seed_vigilance(conn)
    vr.reviser_vigilances(
        conn, search_fn=lambda q, since=None, limit=10: [_article()],
        extractor_fn=_extractor, geocode_fn=_geocode)
    # 2e passage immédiat : la vigilance est en cooldown -> non retraitée
    summary = vr.reviser_vigilances(
        conn, search_fn=lambda q, since=None, limit=10: [_article()],
        extractor_fn=_extractor, geocode_fn=_geocode)
    assert summary["reviewed"] == 0


def test_reviser_ignore_les_scores_faibles(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_vigilance(conn, dict(
        id="vf", banque="BNP Paribas", departement="55",
        titre="BNP Paribas Bar-le-Duc", extrait="", url="http://v/f",
        source="s", date="2026-01-01", score=2, raison="r"))
    summary = vr.reviser_vigilances(
        conn, search_fn=lambda q, since=None, limit=10: [_article()],
        extractor_fn=_extractor, geocode_fn=_geocode, min_score=3)
    assert summary["reviewed"] == 0


def test_reviser_rejette_une_commune_absente_de_la_source(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    _seed_vigilance(conn)

    def wrong_extractor(art):
        closure = _extractor(art)
        closure.update({
            "id": "wrong", "commune": "Plélan-le-Grand",
            "departement": "35", "code_insee": "35223",
        })
        return closure

    def geocode(commune, departement=None):
        if commune == "Plélan-le-Grand":
            return {
                "lat": 48.0, "lon": -2.0, "code_insee": "35223",
                "departement": "35", "commune": commune,
            }
        return _geocode(commune, departement)

    summary = vr.reviser_vigilances(
        conn,
        search_fn=lambda q, since=None, limit=10: [_article()],
        extractor_fn=wrong_extractor,
        geocode_fn=geocode,
    )

    assert summary["closures_created"] == 0
    assert conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0] == 0
