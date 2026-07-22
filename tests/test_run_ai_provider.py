import pytest

import config
import run


class _Result:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self):
        return self.payload


def test_openai_est_fournisseur_principal_sans_cle_anthropic(monkeypatch):
    monkeypatch.setattr(config, "EXTRACTION_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls = []

    def fake_extract(article, aujourdhui):
        calls.append((article, aujourdhui))
        return _Result({"article_type": "out_of_scope", "closures": []})

    monkeypatch.setattr(run.openai_fallback, "extract_openai_structured", fake_extract)
    ai = run._build_ai_extractors("2024-07-01")

    assert ai["provider"] == "openai"
    assert ai["structured"]({"titre": "Test"})["article_type"] == "out_of_scope"
    assert len(calls) == 1


def test_mode_openai_exige_uniquement_openai_api_key(monkeypatch):
    monkeypatch.setattr(config, "EXTRACTION_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    with pytest.raises(SystemExit, match="OPENAI_API_KEY absente"):
        run._build_ai_extractors()


def test_mode_anthropic_reste_reactivable(monkeypatch):
    monkeypatch.setattr(config, "EXTRACTION_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = object()
    monkeypatch.setattr(run.anthropic, "Anthropic", lambda: client)
    monkeypatch.setattr(
        run,
        "extract_structured",
        lambda article, client: _Result({"article_type": "out_of_scope"}),
    )

    ai = run._build_ai_extractors()

    assert ai["provider"] == "anthropic"
    assert ai["structured"]({"titre": "Test"}) == {
        "article_type": "out_of_scope"
    }
