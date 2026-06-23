# tests/test_frontend_smoke.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"

def test_fichiers_presents():
    assert (FRONT / "index.html").exists()
    assert (FRONT / "app.js").exists()
    assert (FRONT / "style.css").exists()

def test_index_reference_maplibre_et_app():
    html = (FRONT / "index.html").read_text(encoding="utf-8")
    assert "maplibre" in html.lower()
    assert "app.js" in html

def test_app_charge_donnees():
    js = (FRONT / "app.js").read_text(encoding="utf-8")
    assert "data.json" in js
    assert "departements.geojson" in js
    assert "maplibregl.Map" in js
