from backend import validation


def test_commune_publiable_rejette_inconnu_et_territoires():
    assert validation.commune_publiable("inconnu") is False
    assert validation.commune_publiable("") is False
    assert validation.commune_publiable("Franche-Comté") is False
    assert validation.commune_publiable("Normandie") is False
    assert validation.commune_publiable("Haute-Loire") is False
    assert validation.commune_publiable("500 grandes villes") is False


def test_commune_publiable_accepte_communes_homonymes():
    assert validation.commune_publiable("La Capelle") is True
    assert validation.commune_publiable("La Capelle-lès-Boulogne") is True


def test_fermeture_publiable_exige_geocodage_insee():
    closure = {"commune": "Rennes", "departement": "35"}
    assert validation.fermeture_publiable(closure, None)[0] is False
    assert validation.fermeture_publiable(closure, {"lat": 48.1, "lon": -1.6, "departement": "35"})[0] is False
    assert validation.fermeture_publiable(
        closure,
        {"lat": 48.1, "lon": -1.6, "departement": "35", "code_insee": "35238"},
    ) == (True, None)


def test_fermeture_publiable_rejette_departement_incoherent():
    closure = {"commune": "La Capelle", "departement": "62"}
    ok, raison = validation.fermeture_publiable(
        closure,
        {"lat": 49.97, "lon": 3.90, "departement": "02", "code_insee": "02141"},
    )
    assert ok is False
    assert "département incohérent" in raison
