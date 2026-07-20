from backend import store
from backend.collectors import laposte_open_data as lp


def _point(point_id="100A", characteristic="Bureau de Poste", **overrides):
    point = {
        "point_id": point_id, "label": "NOMEXY BP", "characteristic": characteristic,
        "address": "1 PLACE DE LA MAIRIE", "postal_code": "88440",
        "locality": "NOMEXY", "code_insee": "88327", "departement": "88",
        "lat": 48.3, "lon": 6.4,
    }
    point.update(overrides)
    return point


def test_normalize_point_preserve_identifiant_et_geographie():
    point = lp.normalize_point({
        "identifiant_a": "100A", "libelle_du_site": "NOMEXY BP",
        "caracteristique_du_site": "Bureau de Poste", "adresse": "1 RUE A",
        "code_postal": 88440, "localite": "NOMEXY", "code_insee": "88327",
        "latitude": 48.3, "longitude": 6.4,
    })
    assert point["point_id"] == "100A"
    assert point["departement"] == "88"
    assert point["postal_code"] == "88440"


def test_sync_initial_est_un_baseline_sans_fermeture(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    result = lp.sync_network(conn, [_point()], "2026-06-01T00:00:00Z")
    assert result == {"status": "updated", "points": 1, "closures": 0, "vigilances": 0}
    assert conn.execute("SELECT active FROM postal_points").fetchone()[0] == 1


def test_conversion_bureau_vers_agence_communale_cree_fermeture_lbp(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    lp.sync_network(conn, [_point()], "2026-06-01T00:00:00Z")
    result = lp.sync_network(
        conn, [_point(characteristic="Agence postale communale")],
        "2026-07-01T00:00:00Z",
    )
    assert result["closures"] == 1
    row = conn.execute(
        "SELECT banque, service_impact, point_postal_apres, evidence_level FROM closures"
    ).fetchone()
    assert row == (
        "La Banque Postale", "conversion_ap", "Agence postale communale", "officiel",
    )


def test_conversion_complete_fermeture_presse_existante(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    lp.sync_network(conn, [_point()], "2026-06-01T00:00:00Z")
    store.upsert_closure(conn, {
        "id": "article", "banque": "La Banque Postale", "commune": "Nomexy",
        "code_insee": "88327", "departement": "88", "type": "fermeture",
        "date_annonce": "2026-05-01", "date_fermeture": None, "statut": "projet",
        "fiabilite": 3, "lat": 48.3, "lon": 6.4, "citation": "Annonce municipale",
    })
    lp.sync_network(
        conn, [_point(characteristic="Agence postale communale")],
        "2026-07-01T00:00:00Z",
    )
    assert conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0] == 1
    assert conn.execute(
        "SELECT statut, fiabilite, service_impact FROM closures WHERE id='article'"
    ).fetchone() == ("confirmé", 5, "conversion_ap")


def test_remplacement_nouvel_identifiant_relais_confirme_immediatement(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    lp.sync_network(conn, [_point()], "2026-06-01T00:00:00Z")
    replacement = _point(
        point_id="200D", characteristic="Relais poste", label="NOMEXY RELAIS",
        address="2 RUE DU COMMERCE",
    )
    result = lp.sync_network(conn, [replacement], "2026-07-01T00:00:00Z")
    assert result["closures"] == 1
    assert conn.execute("SELECT service_impact FROM closures").fetchone()[0] == "conversion_relais"


def test_disparition_isolee_attend_deux_revisions(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    lp.sync_network(conn, [_point()], "2026-05-01T00:00:00Z")
    # Un second point empêche de traiter la révision vide comme une panne API.
    other = _point(point_id="OTHER", locality="EPINAL", code_insee="88160")
    first = lp.sync_network(conn, [other], "2026-06-01T00:00:00Z")
    second = lp.sync_network(conn, [other], "2026-07-01T00:00:00Z")
    assert first["vigilances"] == 1
    assert first["closures"] == 0
    assert second["closures"] == 1


def test_revision_deja_vue_est_ignoree(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    lp.sync_network(conn, [_point()], "rev-1")
    result = lp.sync_network(conn, [_point()], "rev-1")
    assert result["status"] == "unchanged"


def test_detect_banking_cutoff_apres_derniere_ouverture():
    rows = [
        {"date_calendrier": "2026-07-20", "bp_plage_horaire_1": "09:00-17:00"},
        {"date_calendrier": "2026-07-21", "bp_plage_horaire_1": "09:00-17:00"},
    ]
    rows.extend({
        "date_calendrier": f"2026-08-{day:02d}", "bp_plage_horaire_1": "FERME",
    } for day in range(3, 15))
    assert lp.detect_banking_cutoff(rows) == "2026-08-03"


def test_detect_banking_cutoff_refuse_point_toujours_ferme():
    rows = [
        {"date_calendrier": f"2026-08-{day:02d}", "bp_plage_horaire_1": "FERME"}
        for day in range(3, 20)
    ]
    assert lp.detect_banking_cutoff(rows) is None


def test_enrichissement_historique_reconnait_remplacement_relais(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    lp.sync_network(
        conn,
        [_point(point_id="RELAIS", characteristic="Relais poste")],
        "2026-07-01T00:00:00Z",
    )
    store.upsert_closure(conn, {
        "id": "historique", "banque": "La Banque Postale", "commune": "Nomexy",
        "code_insee": "88327", "departement": "88", "type": "fermeture",
        "date_annonce": "2025-05-01", "date_fermeture": "2025-06-01",
        "statut": "confirmé", "fiabilite": 3, "lat": 48.3, "lon": 6.4,
        "citation": "Le bureau a été remplacé par un relais.",
        "service_impact": "fermeture_lbp_complete", "evidence_level": "presse",
    })
    result = lp.enrich_lbp_closures(conn)
    assert result["matched"] == 1
    assert conn.execute(
        "SELECT postal_point_id, service_impact, point_postal_apres, evidence_level "
        "FROM closures WHERE id='historique'"
    ).fetchone() == (
        "RELAIS", "conversion_relais", "Relais poste", "presse+référentiel",
    )
