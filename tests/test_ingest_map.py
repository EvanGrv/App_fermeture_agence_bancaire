from backend.ingest_map import map_result

_TODAY = "2026-07-01"


def _art():
    return {
        "titre": "T",
        "texte": "x",
        "url": "http://a",
        "source": "GN",
        "date": "2026-01-10",
        "departement": "69",
    }


def _res(**kw):
    base = {
        "article_type": "single_closure",
        "closures": [],
        "department_signals": [],
        "vague_signals": [],
    }
    base.update(kw)
    return base


def _clo(**kw):
    base = dict(
        bank="BNP",
        commune="Lyon",
        status="announced",
        closure_type="closure",
        confidence=0.8,
        is_physical_agency=True,
        date_precision="unknown",
        closure_date=None,
        evidence="preuve",
        agency_label="Lyon centre",
        address="1 rue X",
        departement="69",
    )
    base.update(kw)
    return base


def test_map_closure_fields():
    closures, vig = map_result(_res(closures=[_clo()]), _art(), _TODAY)
    assert vig is None
    assert len(closures) == 1
    c = closures[0]
    assert c["banque"] == "BNP Paribas"
    assert c["type"] == "fermeture"
    assert c["statut"] == "projet"
    assert c["fiabilite"] == 4
    assert c["agence_localisation"] == "Lyon centre"
    assert c["adresse"] == "1 rue X"
    assert c["citation"] == "preuve"


def test_map_conversion_postale_qualifie_impact_lbp():
    article = {
        **_art(),
        "titre": "Le bureau de poste de Nomexy transformé en agence postale communale",
    }
    closures, _ = map_result(
        _res(closures=[_clo(bank="La Banque Postale", commune="Nomexy")]),
        article,
        _TODAY,
    )
    assert closures[0]["service_impact"] == "conversion_ap"
    assert closures[0]["point_postal_avant"] == "Bureau de Poste"
    assert closures[0]["point_postal_apres"] == "Agence postale communale"
    assert closures[0]["evidence_level"] == "presse"


def test_map_fermeture_lbp_confirmee_datee_par_publication_si_date_absente():
    article = {
        **_art(),
        "date": "Tue, 15 Apr 2025 07:00:00 GMT",
        "titre": "Le bureau de poste de Nomexy a définitivement fermé",
    }
    closures, _ = map_result(
        _res(closures=[_clo(
            bank="La Banque Postale", commune="Nomexy", status="confirmed",
            closure_date=None, date_precision="unknown",
        )]),
        article,
        _TODAY,
    )
    assert closures[0]["date_fermeture"] == "2025-04-15"
    assert closures[0]["date_fermeture_approx"] == 1
    assert closures[0]["statut_temporel"] == "deja_fermee"


def test_map_projet_lbp_sans_date_ne_devient_pas_fermeture_passee():
    article = {
        **_art(), "date": "Tue, 15 Apr 2025 07:00:00 GMT",
        "titre": "La fermeture du bureau de poste est confirmée mais sans calendrier",
    }
    closures, _ = map_result(
        _res(closures=[_clo(
            bank="La Banque Postale", commune="Nomexy", status="confirmed",
            closure_date=None, date_precision="unknown",
        )]),
        article,
        _TODAY,
    )
    assert closures[0]["date_fermeture"] is None
    assert closures[0]["statut_temporel"] == "inconnu"


def test_map_closure_type_et_statut():
    closures, _ = map_result(
        _res(closures=[_clo(closure_type="merge", status="confirmed")]),
        _art(),
        _TODAY,
    )
    assert closures[0]["type"] == "fusion"
    assert closures[0]["statut"] == "confirmé"


def test_statut_temporel_derive():
    fut, _ = map_result(_res(closures=[_clo(closure_date="2027-01-01")]), _art(), _TODAY)
    assert fut[0]["statut_temporel"] == "a_venir"
    pas, _ = map_result(_res(closures=[_clo(closure_date="2020-01-01")]), _art(), _TODAY)
    assert pas[0]["statut_temporel"] == "deja_fermee"
    ann, _ = map_result(
        _res(closures=[_clo(closure_date=None, status="announced")]),
        _art(),
        _TODAY,
    )
    assert ann[0]["statut_temporel"] == "a_venir"
    conf, _ = map_result(
        _res(closures=[_clo(closure_date=None, status="confirmed")]),
        _art(),
        _TODAY,
    )
    assert conf[0]["statut_temporel"] == "inconnu"


def test_ignore_non_physique_et_banque_inconnue():
    c1 = _clo(is_physical_agency=False)
    c2 = _clo(bank="Boulangerie Dupont")
    closures, _ = map_result(_res(closures=[c1, c2]), _art(), _TODAY)
    assert closures == []


def test_department_signal_vers_vigilance_agregee():
    res = _res(
        article_type="department_signal",
        department_signals=[{
            "bank": "BNP",
            "departement": "18",
            "count": 10,
            "communes_mentioned": ["Bourges"],
            "confidence": 0.6,
            "evidence": "10 agences dans le Cher",
        }],
    )
    closures, vig = map_result(res, _art(), _TODAY)
    assert closures == []
    assert vig is not None
    assert vig["departement"] == "18"
    assert vig["score"] == 3
    assert vig["url"] == "http://a"
    assert "dept" in vig["raison"]


def test_vague_signal_vers_vigilance_sans_departement():
    res = _res(
        article_type="national_signal",
        vague_signals=[{
            "bank": "",
            "scope": "national",
            "count": None,
            "confidence": 0.2,
            "evidence": "vague",
        }],
    )
    closures, vig = map_result(res, _art(), _TODAY)
    assert closures == []
    assert vig is not None and vig["departement"] is None
    assert "vague" in vig["raison"]


def test_vigilance_sans_url_garde_url_null_pour_unique_sqlite():
    article = {**_art(), "url": ""}
    res = _res(
        article_type="department_signal",
        department_signals=[{
            "bank": "BNP",
            "departement": "18",
            "count": 1,
            "communes_mentioned": [],
            "confidence": 0.6,
            "evidence": "signal",
        }],
    )
    _, vig = map_result(res, article, _TODAY)
    assert vig["url"] is None
