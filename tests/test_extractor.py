from backend.extractor import extract, build_messages, Extraction

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

def test_build_messages_sans_prefill():
    msgs = build_messages(_article())
    assert msgs[0]["role"] == "user"
    assert msgs[-1]["role"] != "assistant"
    assert "Société Générale" in msgs[0]["content"]

def test_extract_article_pertinent():
    parsed = Extraction(concerne_banque=True, banque="Société Générale",
                        commune="Rennes", departement="35", type="fermeture",
                        date_fermeture="2026-06-30", statut="projet",
                        fiabilite=4, citation="L'agence fermera le 30 juin 2026.")
    res = extract(_article(), client=FakeClient(parsed))
    assert res["banque"] == "Société Générale"
    assert res["type"] == "fermeture"
    assert res["date_annonce"] == "2026-01-10"
    assert len(res["id"]) == 16
    assert res["lat"] is None and res["code_insee"] is None

def test_extract_rejette_hors_sujet():
    parsed = Extraction(concerne_banque=False, banque="", commune="",
                        departement=None, type="fermeture", date_fermeture=None,
                        statut="rumeur", fiabilite=1, citation="")
    assert extract(_article(), client=FakeClient(parsed)) is None
