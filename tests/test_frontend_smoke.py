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

def test_filtre_temporel_present():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert 'id="f-temporel"' in html
    js = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "f-temporel" in js
    assert "statut_temporel" in js


def test_filtre_temporel_base_sur_la_date_du_jour():
    js = Path("frontend/app.js").read_text(encoding="utf-8")
    # Le statut temporel est recalculé depuis date_fermeture vs aujourd'hui,
    # pas lu depuis le champ figé à l'extraction
    assert "statutTemporelEffectif" in js
    assert "c.statut_temporel === temporel" not in js
    assert "statutTemporelEffectif(c) === temporel" in js


def test_stats_deltas_mensuels_calcules_depuis_created_at():
    js = (FRONT / "app.js").read_text(encoding="utf-8")
    # Plus de deltas codés en dur dans les tuiles de stats
    assert '"+12 ce mois"' not in js
    assert '"+23 ce mois"' not in js
    assert '"+3 ce mois"' not in js
    assert '"+5 ce mois"' not in js
    # Calcul réel basé sur la date d'ajout en base
    assert "addedThisMonth" in js
    assert "newDepartmentsThisMonth" in js


def test_articles_exploration_region_puis_departement_sans_navigation():
    js = (FRONT / "app.js").read_text(encoding="utf-8")
    # Exploration in-page : région -> dossiers départements -> liste d'articles
    assert "exploreRegion" in js
    assert "exploreDep" in js
    assert "articlesExplore" in js
    assert "region-subpanel" in js
    assert "dep-folder" in js
    assert "article-file" in js
    # Délégation d'événements, plus de navigation forcée vers la vue départements
    assert 'data-region="' in js
    assert 'data-dep="' in js
    assert "selectRegion" not in js
    assert 'onclick="selectDepartment' not in js
    # La carte de la vue Articles suit le niveau exploré (région ou département)
    assert "itemsPourCarte" in js

    css = (FRONT / "style.css").read_text(encoding="utf-8")
    assert ".region-subpanel" in css
    assert ".dep-folder" in css


def test_articles_departement_regroupe_les_articles_par_bureau():
    js = (FRONT / "app.js").read_text(encoding="utf-8")
    # Niveau supplémentaire d'exploration : région -> département -> bureau -> articles
    assert "exploreBureau" in js
    assert "bureauKey" in js
    assert "data-bureau=" in js
    assert "bureau-folder" in js
    # L'état d'exploration porte désormais le bureau sélectionné
    assert "bureau:" in js
    css = (FRONT / "style.css").read_text(encoding="utf-8")
    assert ".bureau-folder" in css


def test_vue_departement_affiche_points_et_stats_sans_filtre():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    js = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "Lecture départementale" in html
    assert "department_estimates" in js
    assert "closures_unlocated" in js
    assert "department_signals" in js
    assert "department_signal_count" in js
    # Les points restent affichés dans la vue Départements (plus de masquage)
    assert "const pointVis" not in js
    # Le clic sur un département sélectionne localement, sans toucher au filtre
    assert "depSelectionne" in js
    assert "choisirDepartement" in js
    assert 'document.getElementById("f-dep").value = dep' not in js
    assert 'document.getElementById("f-dep").value = code' not in js
    # Surbrillance au survol et sélection visible
    assert '"feature-state", "hover"' in js
    assert '"feature-state", "selected"' in js
    assert "Estimation départementale" in js
    assert "Signaux non pointés" in js
    assert "Annonces départementales" in js
    assert "Agence sans point précis" in js


def test_popup_point_citation_tronquee_et_date_fermeture_complete():
    js = Path("frontend/app.js").read_text(encoding="utf-8")
    # La citation du popup est bornée pour laisser le bouton fiche accessible
    assert "CITATION_MAX" in js
    assert "extraitCitation" in js
    # Le popup affiche la date de fermeture complète, plus seulement l'année
    assert "date_fermeture: c.date_fermeture" in js
    assert "anneeFermeture" not in js
    assert "formatDate(p.date_fermeture)" in js
    css = Path("frontend/style.css").read_text(encoding="utf-8")
    assert ".popup-date" in css


def test_selection_resultats_affiche_seulement_le_bureau_clique():
    js = Path("frontend/app.js").read_text(encoding="utf-8")
    # Un clic sur un point réduit le panneau Sélection / Résultats au seul
    # bureau cliqué ; fermer le popup restaure la liste filtrée complète
    assert "String(c.id) === String(selectedClosureId)" in js
    assert "deselectClosurePoint" in js
    assert 'popup.on("close"' in js


def test_analytics_vercel_web_analytics_present():
    html = (FRONT / "index.html").read_text(encoding="utf-8")
    # Web Analytics Vercel pour un site statique : script first-party servi
    # depuis l'origine (/_vercel/insights/script.js), sans bundler ni npm.
    assert "/_vercel/insights/script.js" in html
    assert "defer" in html


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
    assert 'default: "24"' in workflow
    assert "lookback-months \"$LOOKBACK_MONTHS\"" in workflow
    assert "|| '24'" in workflow
    assert "720d" in workflow
    assert "data/export/" not in gitignore
