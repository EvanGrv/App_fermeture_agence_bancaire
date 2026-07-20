from backend import vigilance_review as vr


def _geocode_bar_le_duc(commune, departement=None):
    """Géocodeur factice : seule Bar-le-Duc est une commune valide."""
    if vr._cle(commune) == vr._cle("Bar-le-Duc"):
        return {"lat": 48.7, "lon": 5.16, "code_insee": "55029", "departement": "55"}
    return None


def _vigilance_bar_le_duc():
    return {
        "id": "abc",
        "banque": "BNP Paribas",
        "departement": "55",
        "titre": "La BNP Paribas de Bar-le-Duc va fermer",
        "extrait": "Les clients de l'agence s'inquiètent.",
        "score": 4,
    }


# --- generer_requetes -------------------------------------------------------

def test_generer_requetes_banque_commune_domaine():
    queries = vr.generer_requetes(_vigilance_bar_le_duc(), _geocode_bar_le_duc)
    assert queries
    assert any("BNP Paribas" in q and "Bar-le-Duc" in q for q in queries)
    assert any(q.startswith("site:") for q in queries)


def test_generer_requetes_sans_banque_ne_genere_rien():
    vig = _vigilance_bar_le_duc()
    vig["banque"] = None
    assert vr.generer_requetes(vig, _geocode_bar_le_duc) == []


def test_generer_requetes_sans_commune_validable_mais_signal_genere_decouverte():
    vig = _vigilance_bar_le_duc()
    vig["titre"] = "La BNP Paribas va fermer plusieurs agences en Meuse"
    vig["extrait"] = ""
    queries = vr.generer_requetes(vig, lambda c, d=None: None)
    assert queries
    assert any("BNP Paribas" in q and "fermeture" in q for q in queries)


def test_generer_requetes_sans_commune_et_sans_signal_retourne_vide():
    vig = _vigilance_bar_le_duc()
    vig["titre"] = "La BNP Paribas réorganise son réseau"
    vig["extrait"] = ""
    assert vr.generer_requetes(vig, lambda c, d=None: None) == []


# --- candidats_communes : filtrage des faux candidats -----------------------

def test_candidats_communes_ecarte_medias_et_generiques():
    texte = (
        "Ouest-France et L'Est Républicain rapportent que L'agence BNP Paribas "
        "de Bar-le-Duc va fermer. En effet, ICI et Actu confirment."
    )
    candidats = vr.candidats_communes(texte, "BNP Paribas")
    assert "Bar-le-Duc" in candidats
    for faux in ["Ouest-France", "L'Est Républicain", "L'agence", "En",
                 "ICI", "Actu"]:
        assert faux not in candidats


def test_candidats_communes_ignore_urls_google_news_html():
    texte = (
        '<a href="https://news.google.com/rss/articles/CBMi6wFBVV95cUxNT0tlSzdYYWc2VWZnZV9SdDAwN0tHQUpDZE1UZkszR29UTmVG?oc=5">'
        "Le Crédit Agricole ferme son agence de Bar-le-Duc</a>&nbsp;"
        '<font color="#6f6f6f">La Voix du Nord</font>'
    )
    candidats = vr.candidats_communes(texte, "Crédit Agricole")
    assert "Bar-le-Duc" in candidats
    for faux in ["Szd", "Zksz", "La Voix"]:
        assert faux not in candidats


# --- review_vigilance -------------------------------------------------------

def test_review_provider_en_erreur_ne_casse_pas():
    def search_fail(query):
        raise RuntimeError("provider HS")

    out = vr.review_vigilance(
        _vigilance_bar_le_duc(),
        search_fn=search_fail,
        extractor_fn=lambda art: None,
        geocode_fn=_geocode_bar_le_duc,
    )
    # La revue ne dépend plus exclusivement du provider : si la vigilance
    # d'origine contient déjà banque + commune + fermeture, le fallback la publie.
    assert len(out["closures"]) == 1
    assert out["queries_tried"] > 0


def test_review_resultat_publiable_cree_une_fermeture():
    article = {
        "titre": "BNP Paribas ferme son agence de Bar-le-Duc",
        "texte": "La fermeture est prévue le 31 mars 2026.",
        "url": "https://estrepublicain.fr/bar-le-duc-bnp",
        "date": "2026-01-10",
        "source": "L'Est Républicain",
    }

    def search_fn(query):
        return [article]

    def extractor_fn(art):
        return {
            "id": "x1", "banque": "BNP Paribas", "commune": "Bar-le-Duc",
            "code_insee": None, "departement": "55", "type": "fermeture",
            "date_fermeture": "2026-03-31", "statut": "confirmé",
            "fiabilite": 4, "lat": None, "lon": None, "citation": "ferme",
        }

    out = vr.review_vigilance(
        _vigilance_bar_le_duc(),
        search_fn=search_fn,
        extractor_fn=extractor_fn,
        geocode_fn=_geocode_bar_le_duc,
    )
    assert len(out["closures"]) == 1
    cl = out["closures"][0]
    assert cl["commune"] == "Bar-le-Duc"
    assert cl["code_insee"] == "55029"  # enrichi par le géocodeur
    assert article["url"] in out["new_urls"]


def test_review_deduplique_les_urls():
    article = {"titre": "x", "texte": "y", "url": "https://a/1", "date": "2026-01-01"}

    def search_fn(query):
        return [article, article]

    out = vr.review_vigilance(
        _vigilance_bar_le_duc(),
        search_fn=search_fn,
        extractor_fn=lambda art: None,
        geocode_fn=_geocode_bar_le_duc,
    )
    assert out["new_urls"].count("https://a/1") == 1


def test_review_vigilance_origine_cree_fermeture_sans_provider():
    vig = _vigilance_bar_le_duc()
    vig["url"] = "https://pqr/bar-le-duc"
    out = vr.review_vigilance(
        vig,
        search_fn=lambda query: [],
        extractor_fn=lambda art: None,
        geocode_fn=_geocode_bar_le_duc,
    )
    assert len(out["closures"]) == 1
    assert out["closures"][0]["commune"] == "Bar-le-Duc"


def test_review_mode_economique_sans_extracteur_ia():
    vig = _vigilance_bar_le_duc()
    out = vr.review_vigilance(
        vig,
        search_fn=lambda query: [],
        extractor_fn=None,
        geocode_fn=_geocode_bar_le_duc,
    )
    assert len(out["closures"]) == 1
    assert out["articles"] == 1


def test_fallback_signal_multi_communes_ne_publie_pas():
    article = {
        "titre": "BNP Paribas ferme ses agences de Bar-le-Duc et Nancy",
        "texte": "",
    }

    def geocode(commune, departement=None):
        if vr._cle(commune) == vr._cle("Bar-le-Duc"):
            return {"lat": 48.7, "lon": 5.16, "code_insee": "55029", "departement": "55"}
        if vr._cle(commune) == vr._cle("Nancy"):
            return {"lat": 48.69, "lon": 6.18, "code_insee": "54395", "departement": "54"}
        return None

    assert vr.fermeture_depuis_signal(
        article, banque="BNP Paribas", geocode_fn=geocode) is None


def test_fallback_refuse_si_banque_absente_du_signal():
    article = {
        "titre": "NASA : la plus grande bibliothèque de recherche de l’agence ferme",
        "texte": "",
    }
    assert vr.fermeture_depuis_signal(
        article, banque="Société Générale", geocode_fn=_geocode_bar_le_duc) is None


def test_fallback_refuse_agence_non_bancaire_ou_dab_seul():
    articles = [
        {"titre": "Champdôtre. Fermeture exceptionnelle de l’agence postale ce jeudi"},
        {"titre": "Porspoder perd un service avec la fermeture du guichet automatique"},
        {"titre": "Tournay - Crédit Agricole : cinq mois de fermeture pour rénover l’agence"},
    ]
    for article in articles:
        assert vr.fermeture_depuis_signal(
            article, banque="Crédit Agricole", geocode_fn=_geocode_bar_le_duc) is None


def test_fallback_bureau_de_poste_publie_lbp_mono_commune():
    article = {
        "titre": "Bar-le-Duc : le bureau de poste va fermer définitivement",
        "texte": "",
        "date": "2026-07-01",
        "source": "PQR",
        "score": 3,
    }
    closure = vr.fermeture_depuis_signal(
        article,
        banque="La Banque Postale",
        geocode_fn=_geocode_bar_le_duc,
    )
    assert closure is not None
    assert closure["banque"] == "La Banque Postale"
    assert closure["commune"] == "Bar-le-Duc"
    assert closure["statut"] == "projet"


def test_fallback_refuse_agence_postale_communale_sans_indice_bancaire():
    article = {
        "titre": "Bar-le-Duc : l'agence postale communale va fermer",
        "texte": "",
        "score": 3,
    }
    assert vr.fermeture_depuis_signal(
        article,
        banque="La Banque Postale",
        geocode_fn=_geocode_bar_le_duc,
    ) is None


def test_generer_requetes_vigilance_bureau_de_poste_lbp():
    vig = {
        "id": "postal",
        "banque": "La Banque Postale",
        "departement": "55",
        "titre": "Le bureau de poste va fermer en Meuse",
        "extrait": "",
        "score": 3,
    }
    queries = vr.generer_requetes(vig, lambda c, d=None: None, max_queries=20)
    assert queries
    assert any("La Banque Postale" in q for q in queries)
    assert any("bureau de poste" in q for q in queries)


def test_fallback_accepte_titre_agence_locale_singuliere():
    article = {
        "titre": "Dun-sur-Auron. L'agence Caisse d'épargne ferme définitivement",
        "texte": "",
    }

    def geocode(commune, departement=None):
        if vr._cle(commune) == vr._cle("Dun-sur-Auron"):
            return {"lat": 46.88, "lon": 2.57, "code_insee": "18087", "departement": "18"}
        return None

    closure = vr.fermeture_depuis_signal(
        article, banque="Caisse d'Épargne", geocode_fn=geocode)
    assert closure is not None
    assert closure["commune"] == "Dun-sur-Auron"


def test_fallback_refuse_plan_ou_mobilisation_non_agence_precise():
    articles = [
        {"titre": "Une manifestation à Orléans contre la fermeture d'agences de la Caisse d'épargne Loire-Centre"},
        {"titre": "BNP Paribas va fermer 500 agences : votre ville est-elle concernée ?"},
        {"titre": "Fermeture d’agences Crédit Agricole : vers le maintien d’un distributeur de billets à Valmont"},
    ]
    for article in articles:
        assert vr.fermeture_depuis_signal(
            article, banque="Crédit Agricole", geocode_fn=_geocode_bar_le_duc) is None
