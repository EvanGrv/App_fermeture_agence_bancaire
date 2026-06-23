from backend.collectors import sg_locator


def test_detecte_phrase_transfert():
    txt = "À compter du 07/07/2026, votre agence de Piégut-Pluviers transfère ses activités vers Nontron."
    assert sg_locator.est_fermeture_future(txt) is True


def test_detecte_fermeture_definitive():
    assert sg_locator.est_fermeture_future("L'agence fermera définitivement le 16 juillet.") is True


def test_ne_detecte_pas_texte_neutre():
    assert sg_locator.est_fermeture_future("Votre agence vous accueille du lundi au vendredi.") is False


def test_parse_message_date_francaise():
    txt = ("A compter du mardi 7 juillet 2026 l'agence de Strasbourg Meinau (02378) "
           "transfère son activité vers l'agence de Strasbourg Esplanade (02369).")
    r = sg_locator.parse_message(txt)
    assert r["date_fermeture"] == "2026-07-07"
    assert r["code_guichet"] == "02378"
    assert r["destination"] == "Strasbourg Esplanade"


def test_parse_message_date_numerique():
    r = sg_locator.parse_message("À compter du 09/07/2026, transfère ses activités.")
    assert r["date_fermeture"] == "2026-07-09"


def test_crawled_closures(tmp_path):
    import json
    p = tmp_path / "sg_crawl.json"
    p.write_text(json.dumps([
        {"commune": "Bernin", "departement": "38", "adresse": "ZAC Les Michellières, 38190 Bernin",
         "date_fermeture": "2026-07-16", "destination": "Saint-Ismier"},
        {"commune": "", "date_fermeture": None},  # ignoré (incomplet)
    ]), encoding="utf-8")
    cl = sg_locator.crawled_closures(p)
    assert len(cl) == 1
    assert cl[0]["commune"] == "Bernin"
    assert cl[0]["_adresse"].startswith("ZAC")


def test_crawled_closures_absent(tmp_path):
    assert sg_locator.crawled_closures(tmp_path / "absent.json") == []


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
