import importlib

import config
from backend import extractor


def _reload(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("INCLUDE_CREDIT_MUNICIPAL", raising=False)
    else:
        monkeypatch.setenv("INCLUDE_CREDIT_MUNICIPAL", value)
    importlib.reload(config)
    importlib.reload(extractor)


def _restore():
    import os
    os.environ.pop("INCLUDE_CREDIT_MUNICIPAL", None)
    importlib.reload(config)
    importlib.reload(extractor)


def test_credit_municipal_exclu_par_defaut(monkeypatch):
    _reload(monkeypatch, None)
    try:
        assert "Crédit Municipal" not in config.ENSEIGNES
        assert extractor.banque_connue("Crédit Municipal") is False
        assert extractor.normalise_banque("Crédit Municipal de Bordeaux") == "Crédit Municipal"
    finally:
        _restore()


def test_credit_municipal_inclus_si_flag(monkeypatch):
    _reload(monkeypatch, "1")
    try:
        assert "Crédit Municipal" in config.ENSEIGNES
        assert extractor.banque_connue("Crédit Municipal") is True
        assert extractor.normalise_banque("Crédit Municipal") == "Crédit Municipal"
        assert extractor.normalise_banque("Crédit Municipal de Bordeaux") == "Crédit Municipal"
    finally:
        _restore()
