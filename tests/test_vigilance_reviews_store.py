from datetime import datetime, timedelta, timezone

import backend.store as store


def _vigilance(conn, vid, score):
    store.upsert_vigilance(conn, dict(
        id=vid, banque="BNP Paribas", departement="55", titre="t",
        extrait="x", url=f"http://v/{vid}", source="s", date="2026-01-01",
        score=score, raison="r"))


def test_table_vigilance_reviews_creee(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    noms = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "vigilance_reviews" in noms


def test_upsert_review(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_vigilance_review(conn, {
        "id": "v1", "review_status": "done", "queries_tried": 8,
        "new_urls_found": 3, "closures_created": 1})
    row = conn.execute(
        "SELECT review_status, queries_tried, new_urls_found, closures_created "
        "FROM vigilance_reviews WHERE id='v1'").fetchone()
    assert row == ("done", 8, 3, 1)


def test_review_recent_bloque_le_retraitement(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_vigilance_review(conn, {"id": "v1", "review_status": "done"})
    assert store.vigilance_review_recent(conn, "v1", cooldown_days=7) is True


def test_review_ancienne_autorise_le_retraitement(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    vieux = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    store.upsert_vigilance_review(conn, {"id": "v1", "reviewed_at": vieux})
    assert store.vigilance_review_recent(conn, "v1", cooldown_days=7) is False


def test_review_inconnue_nest_pas_recente(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    assert store.vigilance_review_recent(conn, "absente", cooldown_days=7) is False


def test_select_vigilances_a_reviser_filtre_score_et_cooldown(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    _vigilance(conn, "faible", 2)
    _vigilance(conn, "forte", 4)
    _vigilance(conn, "deja", 5)
    store.upsert_vigilance_review(conn, {"id": "deja", "review_status": "done"})

    ids = [v["id"] for v in store.select_vigilances_a_reviser(
        conn, min_score=3, max_per_run=50, cooldown_days=7)]
    assert "forte" in ids        # score >= 3, jamais revue
    assert "faible" not in ids   # score trop bas
    assert "deja" not in ids     # revue récemment


def test_select_vigilances_respecte_max_per_run(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    for i in range(5):
        _vigilance(conn, f"v{i}", 4)
    selection = store.select_vigilances_a_reviser(
        conn, min_score=3, max_per_run=2, cooldown_days=7)
    assert len(selection) == 2


def _vig_source(conn, vid, score, source, titre="signal"):
    store.upsert_vigilance(conn, dict(
        id=vid, banque="BNP Paribas", departement="55", titre=titre,
        extrait="x", url=f"http://v/{vid}", source=source, date="2026-01-01",
        score=score, raison="r"))


def test_select_exclut_legifrance_par_defaut(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    _vig_source(conn, "leg", 5, "Légifrance")
    _vig_source(conn, "pqr", 3, "Ouest-France", titre="BNP Paribas à Reuilly")
    ids = [v["id"] for v in store.select_vigilances_a_reviser(
        conn, min_score=3, max_per_run=50, cooldown_days=7)]
    assert "leg" not in ids
    assert "pqr" in ids


def test_select_inclut_legifrance_si_demande(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    _vig_source(conn, "leg", 5, "Légifrance")
    ids = [v["id"] for v in store.select_vigilances_a_reviser(
        conn, min_score=3, max_per_run=50, cooldown_days=7, inclure_legifrance=True)]
    assert "leg" in ids


def test_select_priorise_pqr_localisee_sur_score_brut(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    # Score brut plus faible mais source PQR + titre localisé -> prioritaire.
    _vig_source(conn, "pqr", 3, "Actu.fr", titre="La BNP Paribas de Bar-le-Duc ferme")
    _vig_source(conn, "web", 5, "GDELT", titre="Réorganisation bancaire nationale")
    selection = store.select_vigilances_a_reviser(
        conn, min_score=3, max_per_run=2, cooldown_days=7)
    assert selection[0]["id"] == "pqr"
