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
