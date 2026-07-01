import json

import pytest

from backend import openai_fallback
from backend.extractor import Extraction, ExtractionResult


def _article():
    return {
        "titre": "BNP ferme son agence de Lyon",
        "texte": "L'agence fermera le 30 juin 2026.",
        "departement": "69",
    }


def _response_json(**kw):
    base = dict(
        concerne_banque=True,
        banque="BNP",
        commune="Lyon",
        departement="69",
        type="fermeture",
        statut_temporel="a_venir",
        date_fermeture="2026-06-30",
        statut="projet",
        fiabilite=4,
        citation="L'agence fermera le 30 juin 2026.",
    )
    base.update(kw)
    return json.dumps(base)


def _structured_content():
    return json.dumps(
        {
            "article_type": "single_closure",
            "source_reliability": "local_press",
            "closures": [
                {
                    "bank": "BNP",
                    "agency_label": "",
                    "commune": "Lyon",
                    "departement": "69",
                    "region": None,
                    "address": "",
                    "closure_date": "2026-06-30",
                    "date_precision": "exact",
                    "status": "announced",
                    "closure_type": "closure",
                    "is_physical_agency": True,
                    "confidence": 0.8,
                    "evidence": "L'agence fermera le 30 juin 2026.",
                }
            ],
            "department_signals": [],
            "vague_signals": [],
            "confidence": 0.8,
            "needs_sonnet": False,
            "reason": "",
        }
    )


def test_extract_openai_parse_et_enregistre_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    budget_path = tmp_path / "budget.json"
    appels = []

    def fetch(url, api_key, payload):
        appels.append((url, api_key, payload))
        return {
            "choices": [{"message": {"content": _response_json()}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }

    res = openai_fallback.extract_openai(
        _article(), "2026-06-01", fetch=fetch, budget_path=budget_path
    )
    assert isinstance(res, Extraction)
    assert res.banque == "BNP"
    assert appels[0][2]["response_format"]["json_schema"]["strict"] is True
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    assert budget["calls"] == 1
    assert budget["spent_eur"] > 0


def test_extract_openai_bloque_budget_avant_appel(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BUDGET_EUR", "0.000001")
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "1000")
    budget_path = tmp_path / "budget.json"

    def fetch(*args, **kwargs):
        raise AssertionError("ne doit pas appeler OpenAI quand le budget est dépassé")

    with pytest.raises(openai_fallback.OpenAIBudgetExceeded):
        openai_fallback.extract_openai(
            _article(), "2026-06-01", fetch=fetch, budget_path=budget_path
        )


def test_schema_inclut_date_approx():
    from backend.openai_fallback import _schema

    s = _schema()
    assert "date_fermeture_approx" in s["properties"]
    assert s["properties"]["date_fermeture_approx"] == {"type": "boolean"}
    assert "date_fermeture_approx" in s["required"]


def test_extract_openai_structured_parse_et_enregistre_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    budget_path = tmp_path / "budget.json"
    appels = []

    def fetch(url, api_key, payload):
        appels.append((url, api_key, payload))
        return {
            "choices": [{"message": {"content": _structured_content()}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }

    out = openai_fallback.extract_openai_structured(
        _article(), "2026-07-01", fetch=fetch, budget_path=budget_path
    )
    assert isinstance(out, ExtractionResult)
    assert out.article_type == "single_closure"
    assert out.closures[0].commune == "Lyon"
    assert appels[0][2]["response_format"]["json_schema"]["name"] == "extraction_structuree"
    assert appels[0][2]["response_format"]["json_schema"]["strict"] is True
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    assert budget["calls"] == 1


def test_schema_structured_a_les_cles():
    sch = openai_fallback._schema_structured()
    assert sch["type"] == "object"
    assert "closures" in sch["properties"]
    assert "department_signals" in sch["properties"]
    assert "vague_signals" in sch["properties"]
    assert "confidence" in sch["properties"]
