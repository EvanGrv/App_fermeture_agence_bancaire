import json
from pathlib import Path
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
