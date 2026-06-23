import json
from pathlib import Path
import requests
from backend.collectors import gdelt

FIXT = Path(__file__).parent / "fixtures" / "gdelt_sample.json"

def test_parse_response():
    payload = json.loads(FIXT.read_text(encoding="utf-8"))
    arts = gdelt.parse_response(payload)
    assert len(arts) == 2
    a = arts[0]
    assert a["titre"] == "Crédit Mutuel ferme une agence"
    assert a["url"] == "https://ex.fr/g1"
    assert a["source"] == "GDELT"
    assert set(a) >= {"titre", "texte", "url", "date", "source", "departement"}

def test_parse_response_vide():
    assert gdelt.parse_response({}) == []

def test_collect_injecte_fetch():
    payload = json.loads(FIXT.read_text(encoding="utf-8"))
    arts = gdelt.collect(fetch=lambda url: payload)
    assert len(arts) == 2

def test_collect_retry_429_retry_after(monkeypatch):
    payload = json.loads(FIXT.read_text(encoding="utf-8"))
    sleeps = []
    calls = {"n": 0}

    def fake_sleep(seconds):
        sleeps.append(seconds)

    def fake_fetch(url):
        calls["n"] += 1
        if calls["n"] == 1:
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "7"
            raise requests.exceptions.HTTPError(response=response)
        return payload

    monkeypatch.setattr(gdelt.time, "sleep", fake_sleep)

    arts = gdelt.collect(fetch=fake_fetch, retries=1, base_wait=1.0)

    assert len(arts) == 2
    assert calls["n"] == 2
    assert sleeps == [7.0]
