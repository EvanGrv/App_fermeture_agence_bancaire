from backend.extractor import extract, build_messages, Extraction, normalise_banque

AUJ = "2026-06-01"  # date du jour fixe pour des tests déterministes

class FakeResp:
    def __init__(self, parsed):
        self.parsed_output = parsed

class FakeMessages:
    def __init__(self, parsed):
        self._parsed = parsed
    def parse(self, **kw):
        return FakeResp(self._parsed)

class FakeClient:
    def __init__(self, parsed):
        self.messages = FakeMessages(parsed)

def _article():
    return {"titre": "La Société Générale ferme son agence de Rennes",
            "texte": "L'agence fermera le 30 juin 2026.",
            "url": "http://x", "date": "2026-01-10",
            "source": "Google News", "departement": "35"}

def _extraction(**kw):
    base = dict(concerne_banque=True, banque="Société Générale", commune="Rennes",
                departement="35", type="fermeture", statut_temporel="a_venir",
                date_fermeture="2026-06-30", statut="projet", fiabilite=4,
                citation="L'agence fermera le 30 juin 2026.")
    base.update(kw)
    return Extraction(**base)

def test_build_messages_sans_prefill():
    msgs = build_messages(_article(), aujourdhui=AUJ)
    assert msgs[0]["role"] == "user"
    assert msgs[-1]["role"] != "assistant"
    assert "Société Générale" in msgs[0]["content"]
    assert AUJ in msgs[0]["content"]

def test_extract_article_pertinent():
    res = extract(_article(), client=FakeClient(_extraction()), aujourdhui=AUJ)
    assert res["banque"] == "Société Générale"
    assert res["type"] == "fermeture"
    assert res["date_annonce"] == "2026-01-10"
    assert len(res["id"]) == 16
    assert res["lat"] is None and res["code_insee"] is None

def test_extract_rejette_hors_sujet():
    parsed = _extraction(concerne_banque=False)
    assert extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ) is None

def test_extract_rejette_deja_fermee():
    parsed = _extraction(statut_temporel="deja_fermee")
    assert extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ) is None

def test_extract_rejette_date_passee():
    parsed = _extraction(statut_temporel="inconnu", date_fermeture="2025-01-15")
    assert extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ) is None

def test_normalise_banque():
    assert normalise_banque("Crédit agricole") == "Crédit Agricole"
    assert normalise_banque("BNP") == "BNP Paribas"
    assert normalise_banque("Banque Postale") == "La Banque Postale"
    assert normalise_banque("Inconnue SA") == "Inconnue SA"

def test_normalise_banque_variantes_regionales():
    assert normalise_banque("Crédit Agricole Loire Haute-Loire") == "Crédit Agricole"
    assert normalise_banque("SG SMC") == "Société Générale"
    assert normalise_banque("BPGO") == "Banque Populaire"
    assert normalise_banque("CEBPL") == "Caisse d'Épargne"

def test_extract_normalise_banque():
    parsed = _extraction(banque="crédit agricole")
    res = extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ)
    assert res["banque"] == "Crédit Agricole"

def test_extract_exclut_banque_postale():
    parsed = _extraction(banque="La Banque Postale")
    assert extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ) is None
