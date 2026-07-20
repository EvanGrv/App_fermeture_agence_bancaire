from backend import vigilance


def test_depuis_article_signal_legifrance():
    article = {
        "titre": "Accord relatif à la restructuration de Société Générale",
        "texte": "Le texte évoque des fermetures d'agences bancaires.",
        "url": "https://legifrance.gouv.fr/x",
        "date": "2026-01-10",
        "source": "Légifrance",
        "departement": None,
    }
    v = vigilance.depuis_article(article, raison="signal faible")
    assert v["banque"] == "Société Générale"
    assert v["score"] >= 4
    assert v["raison"] == "signal faible"
    assert len(v["id"]) == 16


def test_depuis_article_ignore_hors_sujet():
    article = {"titre": "Météo", "texte": "soleil", "url": "http://x"}
    assert vigilance.depuis_article(article) is None


def test_depuis_article_bureau_de_poste_candidate_lbp():
    article = {
        "titre": "Le bureau de poste de Bar-le-Duc va fermer",
        "texte": "Les habitants redoutent la perte de ce service public.",
        "url": "https://pqr/poste-bar-le-duc",
        "date": "2026-07-01",
        "source": "PQR",
    }
    v = vigilance.depuis_article(article, raison="candidat postal")
    assert v is not None
    assert v["banque"] == "La Banque Postale"
    assert v["score"] >= 3


def test_titre_postal_prioritaire_sur_banque_parasite_dans_extrait():
    article = {
        "titre": "Le bureau de poste de Niort-Sainte-Pezenne va fermer ses portes",
        "texte": "<a>Société Générale annonce par ailleurs une nouvelle agence</a>",
        "url": "https://news.google.com/poste-niort",
        "source": "Google News",
    }
    assert vigilance.depuis_article(article)["banque"] == "La Banque Postale"


def test_reclassify_postal_vigilances_force_nouvelle_revue(tmp_path):
    from backend import store

    conn = store.init_db(tmp_path / "t.db")
    store.upsert_vigilance(conn, {
        "id": "postal", "banque": "Société Générale", "departement": "45",
        "titre": "Le bureau de poste des Blossières fermera définitivement",
        "extrait": "", "url": "https://example.test/poste", "source": "Google News",
        "date": "2026-07-01", "score": 4, "raison": "signal",
    })
    store.upsert_vigilance_review(conn, {"id": "postal", "review_status": "done"})

    assert vigilance.reclassify_postal_vigilances(conn) == 1
    assert conn.execute("SELECT banque FROM vigilances").fetchone()[0] == "La Banque Postale"
    assert conn.execute("SELECT COUNT(*) FROM vigilance_reviews").fetchone()[0] == 0
