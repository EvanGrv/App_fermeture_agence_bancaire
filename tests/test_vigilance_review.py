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


def test_generer_requetes_sans_commune_validable_retourne_vide():
    vig = _vigilance_bar_le_duc()
    vig["titre"] = "La BNP Paribas réorganise son réseau"
    vig["extrait"] = ""
    # Aucun nom propre ne géocode -> pas de requête.
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
    assert out["closures"] == []
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
