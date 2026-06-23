from backend.collectors import presse_pro


def test_collect_sans_credentials_retourne_vide(monkeypatch):
    for env in presse_pro.CREDENTIALS:
        monkeypatch.delenv(env, raising=False)
    assert presse_pro.collect() == []


def test_collect_avec_credentials_reste_scaffold(monkeypatch):
    for env in presse_pro.CREDENTIALS:
        monkeypatch.setenv(env, "x")
    assert presse_pro.collect() == []
