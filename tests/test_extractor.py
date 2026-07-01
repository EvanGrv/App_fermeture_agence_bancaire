from datetime import date, timedelta
import config
from backend.extractor import (
    ClosureItem,
    DeptSignal,
    Extraction,
    ExtractionResult,
    VagueSignal,
    build_messages,
    extract,
    extract_structured,
    normalise_banque,
    should_escalate_structured,
    _retenir_fermeture,
    banque_connue,
)

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

class SequenceMessages:
    def __init__(self, parsed_outputs):
        self._parsed_outputs = list(parsed_outputs)
        self.models = []
    def parse(self, **kw):
        self.models.append(kw.get("model"))
        return FakeResp(self._parsed_outputs.pop(0))

class SequenceClient:
    def __init__(self, parsed_outputs):
        self.messages = SequenceMessages(parsed_outputs)

class FakeTransientError(Exception):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code

class StructuredSequenceMessages:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []
    def parse(self, **kw):
        self.calls.append(kw)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeResp(result)

class StructuredSequenceClient:
    def __init__(self, results):
        self.messages = StructuredSequenceMessages(results)

class FlakyMessages:
    def __init__(self, parsed, failures):
        self._parsed = parsed
        self._failures = list(failures)
        self.calls = 0
    def parse(self, **kw):
        self.calls += 1
        if self._failures:
            raise self._failures.pop(0)
        return FakeResp(self._parsed)

class FlakyClient:
    def __init__(self, parsed, failures):
        self.messages = FlakyMessages(parsed, failures)

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
    # nouveaux champs de phase 1
    assert res["statut_temporel"] == "a_venir"
    assert res["date_fermeture_approx"] == 0

def test_extract_retry_erreur_anthropic_transitoire(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "2")
    monkeypatch.setenv("ANTHROPIC_RETRY_BASE_SECONDS", "0")
    client = FlakyClient(_extraction(), [FakeTransientError(529)])
    res = extract(_article(), client=client, aujourdhui=AUJ)
    assert res["banque"] == "Société Générale"
    assert client.messages.calls == 2

def test_extract_ne_retry_pas_erreur_non_transitoire(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "2")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = FlakyClient(_extraction(), [FakeTransientError(401)])
    try:
        extract(_article(), client=client, aujourdhui=AUJ)
    except FakeTransientError:
        pass
    else:
        assert False, "l'erreur non transitoire doit remonter"
    assert client.messages.calls == 1

def test_extract_fallback_openai_apres_erreur_transitoire(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_ENABLED", False)
    client = FlakyClient(_extraction(), [FakeTransientError(529)])
    attendu = _extraction(banque="BNP")

    def fake_openai(article, aujourdhui):
        return attendu

    monkeypatch.setattr("backend.openai_fallback.extract_openai", fake_openai)
    res = extract(_article(), client=client, aujourdhui=AUJ)
    assert res["banque"] == "BNP Paribas"
    assert client.messages.calls == 1

def test_extract_fallback_sonnet_si_haiku_non_publiable(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_ENABLED", True)
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-test")
    client = SequenceClient([
        _extraction(concerne_banque=False),
        _extraction(banque="BNP"),
    ])
    res = extract(_article(), client=client, model="claude-haiku-test", aujourdhui=AUJ)
    assert res["banque"] == "BNP Paribas"
    assert client.messages.models == ["claude-haiku-test", "claude-sonnet-test"]

def test_extract_ne_fallback_pas_si_haiku_suffit(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_ENABLED", True)
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-test")
    client = SequenceClient([_extraction()])
    res = extract(_article(), client=client, model="claude-haiku-test", aujourdhui=AUJ)
    assert res["banque"] == "Société Générale"
    assert client.messages.models == ["claude-haiku-test"]

def test_extract_rejette_hors_sujet():
    parsed = _extraction(concerne_banque=False)
    assert extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ) is None

def test_extract_retient_deja_fermee_dans_fenetre():
    # deja_fermee avec date dans la fenêtre (pas de floor) -> on garde
    parsed = _extraction(statut_temporel="deja_fermee", date_fermeture="2025-06-01")
    res = extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ)
    assert res is not None
    assert res["statut_temporel"] == "deja_fermee"


def test_extract_rejette_deja_fermee_trop_ancienne():
    # deja_fermee avec date < floor -> rejeté (-> vigilance)
    parsed = _extraction(statut_temporel="deja_fermee", date_fermeture="2024-03-01")
    res = extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ, floor="2025-01-01")
    assert res is None


def test_extract_rejette_deja_fermee_sans_date():
    # deja_fermee sans date -> rejeté (-> vigilance), indépendamment du floor
    parsed = _extraction(statut_temporel="deja_fermee", date_fermeture=None)
    assert extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ) is None


def test_extract_retient_inconnu_avec_date_recente():
    # inconnu avec date récente et pas de floor -> on garde
    parsed = _extraction(statut_temporel="inconnu", date_fermeture="2025-01-15")
    res = extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ)
    assert res is not None
    assert res["statut_temporel"] == "inconnu"


def test_extract_rejette_inconnu_avec_date_trop_ancienne():
    # inconnu avec date < floor -> rejeté
    parsed = _extraction(statut_temporel="inconnu", date_fermeture="2025-01-15")
    res = extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ, floor="2025-06-01")
    assert res is None


def test_extract_rejette_temporalite_inconnue_sans_date():
    parsed = _extraction(statut_temporel="inconnu", date_fermeture=None)
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

def test_extract_inclut_banque_postale():
    parsed = _extraction(banque="La Banque Postale")
    res = extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ)
    assert res is not None
    assert res["banque"] == "La Banque Postale"

def test_build_messages_demande_agence_nominative():
    message = build_messages({
        "titre": "Suppressions de postes et fermetures d'agences au Crédit Agricole",
        "texte": "Les salariés sont appelés à la grève, sans liste de communes.",
        "departement": None,
    }, aujourdhui=AUJ)[0]["content"]
    assert "commune précise" in message
    assert "N'invente jamais de commune" in message


def _closure_item(**kw):
    base = dict(
        bank="BNP",
        commune="Lyon",
        status="announced",
        closure_type="closure",
        confidence=0.7,
        evidence="L'agence de Lyon fermera.",
    )
    base.update(kw)
    return ClosureItem(**base)


def test_extraction_result_listes_typees():
    out = ExtractionResult.model_validate({
        "article_type": "department_signal",
        "closures": [_closure_item().model_dump()],
        "department_signals": [{
            "bank": "BNP",
            "departement": "69",
            "communes_mentioned": ["Lyon"],
            "confidence": 0.6,
        }],
        "vague_signals": [{
            "bank": "BNP",
            "scope": "regional",
            "confidence": 0.4,
        }],
    })
    assert isinstance(out.closures[0], ClosureItem)
    assert isinstance(out.department_signals[0], DeptSignal)
    assert isinstance(out.vague_signals[0], VagueSignal)
    assert out.department_signals[0].communes_mentioned == ["Lyon"]


def test_extract_structured_single_closure():
    result = ExtractionResult(article_type="single_closure", closures=[_closure_item()])
    client = StructuredSequenceClient([result])
    out = extract_structured(_article(), client=client, aujourdhui=AUJ)
    assert out.article_type == "single_closure"
    assert len(out.closures) == 1
    assert out.closures[0].commune == "Lyon"
    assert client.messages.calls[0]["output_format"].__name__ == "ExtractionResult"
    assert client.messages.calls[0]["max_tokens"] == 2048


def test_extract_structured_list_closures():
    result = ExtractionResult(
        article_type="list_closures",
        closures=[
            _closure_item(commune="Bessines"),
            _closure_item(commune="Tulle"),
            _closure_item(commune="Guéret"),
        ],
    )
    out = extract_structured(_article(), client=StructuredSequenceClient([result]), aujourdhui=AUJ)
    assert len(out.closures) == 3


def test_extract_structured_out_of_scope_non_none():
    result = ExtractionResult(article_type="out_of_scope")
    out = extract_structured(_article(), client=StructuredSequenceClient([result]), aujourdhui=AUJ)
    assert out is not None
    assert out.closures == []
    assert out.department_signals == []


def test_extract_structured_fallback_sonnet_sur_erreur(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "0")
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_ENABLED", True)
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-test")
    result = ExtractionResult(article_type="single_closure", closures=[_closure_item()])
    client = StructuredSequenceClient([FakeTransientError(529), result])
    out = extract_structured(_article(), client=client, model="claude-haiku-test", aujourdhui=AUJ)
    assert len(out.closures) == 1
    assert client.messages.calls[0]["model"] == "claude-haiku-test"
    assert client.messages.calls[1]["model"] == "claude-sonnet-test"


def test_should_escalate_structured_signaux_contenu():
    assert should_escalate_structured(
        ExtractionResult(article_type="single_closure", confidence=0.9, needs_sonnet=True)
    )
    assert should_escalate_structured(
        ExtractionResult(article_type="ambiguous", confidence=0.9)
    )
    assert should_escalate_structured(
        ExtractionResult(article_type="single_closure", confidence=0.4)
    )
    assert should_escalate_structured(
        ExtractionResult(article_type="list_closures", confidence=0.9, closures=[])
    )
    assert should_escalate_structured(
        ExtractionResult(article_type="department_signal", confidence=0.9, department_signals=[])
    )
    assert not should_escalate_structured(
        ExtractionResult(article_type="single_closure", confidence=0.9, closures=[_closure_item()])
    )


def test_extract_structured_escalade_sonnet_sur_ambigu(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_ENABLED", True)
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-test")
    monkeypatch.setattr(config, "STRUCTURED_SONNET_ESCALATION_ENABLED", True)
    haiku = ExtractionResult(article_type="ambiguous", confidence=0.4, needs_sonnet=True)
    sonnet = ExtractionResult(
        article_type="single_closure",
        confidence=0.9,
        closures=[_closure_item(commune="Rennes")],
    )
    client = StructuredSequenceClient([haiku, sonnet])
    out = extract_structured(_article(), client=client, model="claude-haiku-test", aujourdhui=AUJ)
    assert out.article_type == "single_closure"
    assert out.confidence == 0.9
    assert client.messages.calls[0]["model"] == "claude-haiku-test"
    assert client.messages.calls[1]["model"] == "claude-sonnet-test"
    assert "RELIS" in client.messages.calls[1]["messages"][0]["content"]


def test_extract_structured_pas_escalade_si_desactive(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_ENABLED", True)
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-test")
    monkeypatch.setattr(config, "STRUCTURED_SONNET_ESCALATION_ENABLED", False)
    haiku = ExtractionResult(article_type="ambiguous", confidence=0.4, needs_sonnet=True)
    client = StructuredSequenceClient([haiku])
    out = extract_structured(_article(), client=client, model="claude-haiku-test", aujourdhui=AUJ)
    assert out is haiku
    assert len(client.messages.calls) == 1


def test_extract_structured_garde_haiku_si_sonnet_contenu_echoue(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "0")
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_ENABLED", True)
    monkeypatch.setattr(config, "ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-test")
    monkeypatch.setattr(config, "STRUCTURED_SONNET_ESCALATION_ENABLED", True)
    haiku = ExtractionResult(article_type="ambiguous", confidence=0.4, needs_sonnet=True)
    client = StructuredSequenceClient([haiku, FakeTransientError(529)])
    out = extract_structured(_article(), client=client, model="claude-haiku-test", aujourdhui=AUJ)
    assert out is haiku
    assert len(client.messages.calls) == 2


def test_la_banque_postale_est_suivie():
    assert "La Banque Postale" in config.ENSEIGNES
    assert config.EXCLURE_BANQUES == []
    assert normalise_banque("La Banque Postale") == "La Banque Postale"


def test_credit_cooperatif_canonique():
    assert "Crédit Coopératif" in config.ENSEIGNES
    assert normalise_banque("crédit coopératif") == "Crédit Coopératif"


# ---------------------------------------------------------------------------
# Tests pour _retenir_fermeture (Step 1 TDD)
# ---------------------------------------------------------------------------

def test_passee_recente_est_retenue():
    # déjà fermée mais dans la fenêtre -> on garde
    ok = _retenir_fermeture("deja_fermee", "2025-06-01", floor="2025-01-01",
                            aujourdhui="2026-06-25")
    assert ok is True


def test_passee_trop_ancienne_est_rejetee():
    ok = _retenir_fermeture("deja_fermee", "2024-03-01", floor="2025-01-01",
                            aujourdhui="2026-06-25")
    assert ok is False


def test_passee_sans_date_est_rejetee():
    ok = _retenir_fermeture("deja_fermee", None, floor="2025-01-01",
                            aujourdhui="2026-06-25")
    assert ok is False


def test_a_venir_est_retenue_sans_date():
    ok = _retenir_fermeture("a_venir", None, floor="2025-01-01",
                            aujourdhui="2026-06-25")
    assert ok is True


# ---------------------------------------------------------------------------
# Task 16 — Part 1: robust bank normalization
# ---------------------------------------------------------------------------

def test_normalise_banque_gere_tiret():
    """BNP-Paribas (avec tiret) doit être canonisé en BNP Paribas."""
    assert normalise_banque("BNP-Paribas") == "BNP Paribas"


def test_normalise_banque_regionale_tiret():
    """Caisse d'Épargne Loire Centre avec tiret → enseigne canonique.
    Variante utilisée : 'Caisse d'épargne Loire-Centre' (tiret dans Loire-Centre)
    qui doit mapper sur 'Caisse d'Épargne Loire Centre' dans MARQUES_REGIONALES
    et retourner le canonical 'Caisse d'Épargne'.
    """
    assert normalise_banque("Caisse d'épargne Loire-Centre") == "Caisse d'Épargne"


def test_banque_connue():
    assert banque_connue("BNP Paribas") is True
    assert banque_connue("") is False
    assert banque_connue("BforBank") is False


def test_extract_rejette_banque_inconnue():
    """extract() doit retourner None si la banque n'est pas dans le périmètre."""
    parsed = _extraction(banque="", concerne_banque=True)
    assert extract(_article(), client=FakeClient(parsed), aujourdhui=AUJ) is None
