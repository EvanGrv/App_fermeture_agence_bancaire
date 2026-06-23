from backend.collectors import sg_locator


def test_detecte_phrase_transfert():
    txt = "À compter du 07/07/2026, votre agence de Piégut-Pluviers transfère ses activités vers Nontron."
    assert sg_locator.est_fermeture_future(txt) is True


def test_detecte_fermeture_definitive():
    assert sg_locator.est_fermeture_future("L'agence fermera définitivement le 16 juillet.") is True


def test_ne_detecte_pas_texte_neutre():
    assert sg_locator.est_fermeture_future("Votre agence vous accueille du lundi au vendredi.") is False


def test_seed_closures_structure():
    cl = sg_locator.seed_closures()
    assert len(cl) == 6
    c = cl[0]
    assert c["banque"] == "Société Générale"
    assert c["type"] == "fermeture"
    assert c["statut"] == "confirmé"
    assert c["date_fermeture"].startswith("2026-")
    assert c["_adresse"]            # adresse pour géocodage précis
    assert len(c["id"]) == 16
    assert "transfère ses activités" in c["citation"]
