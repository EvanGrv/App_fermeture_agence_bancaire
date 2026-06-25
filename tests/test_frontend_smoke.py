# tests/test_frontend_smoke.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"

def test_fichiers_presents():
    assert (ROOT / "index.html").exists()
    assert (FRONT / "index.html").exists()
    assert (FRONT / "app.js").exists()
    assert (FRONT / "style.css").exists()

def test_index_racine_redirige_vers_frontend():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "/frontend" in html

def test_index_reference_maplibre_et_app():
    html = (FRONT / "index.html").read_text(encoding="utf-8")
    assert "maplibre" in html.lower()
    assert "/frontend/app.js" in html
    assert "/frontend/style.css" in html

def test_app_charge_donnees():
    js = (FRONT / "app.js").read_text(encoding="utf-8")
    assert "data.json" in js
    assert "departements.geojson" in js
    assert "maplibregl.Map" in js

def test_relance_pipeline_presets_et_api():
    html = (FRONT / "index.html").read_text(encoding="utf-8")
    js = (FRONT / "app.js").read_text(encoding="utf-8")

    for months in ("6", "18", "24", "36"):
        assert f'data-lookback-months="{months}"' in html
    assert 'id="pipeline-since"' in html
    assert 'id="run-pipeline"' in html
    assert 'id="pipeline-progress-bar"' in html
    assert 'id="pipeline-progress-value"' in html
    assert "/api/pipeline/run" in js
    assert "/api/pipeline/status/" in js
    assert "127.0.0.1:8010" in js
    assert "127.0.0.1:8011" in js
    assert "GitHub Actions" in js
    assert "isHostedDeployment" in js

def test_telechargement_excel_genere_un_vrai_xlsx():
    js = (FRONT / "app.js").read_text(encoding="utf-8")

    assert 'addEventListener("click", () => telechargerExcel())' in js
    assert 'singleId = typeof singleId === "string" ? singleId : ""' in js
    assert ".xlsx" in js
    assert ".xls`" not in js
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in js
    assert "[Content_Types].xml" in js
    assert "xl/worksheets/sheet1.xml" in js
    assert "autoFilter" in js
    assert "state=\"frozen\"" in js

def test_deploiement_vercel_github_actions_configure():
    root = ROOT
    assert (root / "vercel.json").exists()
    assert (root / ".github" / "workflows" / "update-data.yml").exists()

    vercel = (root / "vercel.json").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "update-data.yml").read_text(encoding="utf-8")
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")

    assert "data/export" in vercel
    assert "python run.py" in workflow
    assert "data/export" in workflow
    assert "ANTHROPIC_API_KEY" in workflow
    assert "data/export/" not in gitignore
