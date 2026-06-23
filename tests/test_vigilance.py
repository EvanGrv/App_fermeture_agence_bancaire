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
