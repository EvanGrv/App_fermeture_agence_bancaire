# tests/test_geojson.py
import json
from backend import geojson

SAMPLE = ('{"type":"FeatureCollection","features":[{"type":"Feature",'
          '"properties":{"code":"35","nom":"Ille-et-Vilaine"},'
          '"geometry":{"type":"Polygon","coordinates":[]}}]}')

def test_telecharge_si_absent(tmp_path):
    p = tmp_path / "dep.geojson"
    appels = []
    def fetch(url):
        appels.append(url)
        return SAMPLE
    res = geojson.ensure_departements_geojson(path=p, fetch=fetch)
    assert res == p
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["features"][0]["properties"]["code"] == "35"
    assert len(appels) == 1

def test_idempotent_si_present(tmp_path):
    p = tmp_path / "dep.geojson"
    p.write_text(SAMPLE, encoding="utf-8")
    def fetch(url):
        raise AssertionError("ne doit pas re-télécharger")
    geojson.ensure_departements_geojson(path=p, fetch=fetch)
    assert p.exists()
