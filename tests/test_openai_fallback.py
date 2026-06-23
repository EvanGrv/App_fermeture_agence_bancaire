import json

import pytest

from backend import openai_fallback
from backend.extractor import Extraction


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
