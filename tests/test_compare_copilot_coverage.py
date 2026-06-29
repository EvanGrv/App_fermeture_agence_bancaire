import json
from pathlib import Path

from openpyxl import Workbook

from tools.compare_copilot_coverage import (
    apply_reliability,
    classify_coverage,
    dept_name_to_code,
    load_copilot_rows,
    load_overrides,
)


def _row(banque="BNP Paribas", commune="Lyon", departement="Rhône", lat="", lon="",
         agence_localisation="", source="V2", url=""):
    return {"banque": banque, "commune": commune, "departement": departement,
            "lat": lat, "lon": lon, "agence_localisation": agence_localisation,
            "commune_originale": "", "source": source, "url": url,
            "statut_copilot": "", "commentaires": "", "score": ""}


def _make_xlsx(path: Path, rows: list[list]) -> Path:
    """Écrit un xlsx avec l'en-tête réel de l'Excel Copilot puis les lignes données."""
    wb = Workbook()
    ws = wb.active
    header = ["²", "Agence / localisation", "Adresse la plus complète possible",
              "Commune", "Département", "Région", "Latitude", "Longitude",
              "Date de fermeture", "Précision date", "Source principale",
              "Lien source", "Sources de localisation", "Lien localisation",
              "Score confiance", "Statut", "Commentaires"]
    ws.append(header)
    for r in rows:
        ws.append(r + [""] * (len(header) - len(r)))
    wb.save(path)
    return path


def test_load_copilot_rows_maps_columns(tmp_path):
    path = _make_xlsx(tmp_path / "ref.xlsx", [
        ["BNP Paribas", "Chalon - av. de Paris", "141 avenue de Paris, 71100 Chalon",
         "Chalon-sur-Saône", "Saône-et-Loire", "BFC", 46.79, 4.84,
         "2026-06-30", "exacte", "Fichier principal V2", "", "", "", 96, "Confirmé", "note"],
    ])
    rows = load_copilot_rows(path)
    assert len(rows) == 1
    r = rows[0]
    assert r["banque"] == "BNP Paribas"
    assert r["commune"] == "Chalon-sur-Saône"
    assert r["departement"] == "Saône-et-Loire"
    assert r["source"] == "Fichier principal V2"
    assert r["url"] == ""
    assert r["score"] == "96"
    assert float(r["lat"]) == 46.79


def test_load_copilot_rows_skips_blank_rows(tmp_path):
    path = _make_xlsx(tmp_path / "ref.xlsx", [
        ["BNP Paribas", "", "", "Lyon", "Rhône", "", "", "", "", "", "V2", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ])
    rows = load_copilot_rows(path)
    assert len(rows) == 1


def test_dept_name_to_code():
    assert dept_name_to_code("Indre-et-Loire") == "37"
    assert dept_name_to_code("saône-et-loire") == "71"  # insensible casse/accents
    assert dept_name_to_code("Pays Imaginaire") is None
    assert dept_name_to_code("") is None


def test_load_overrides_missing_file_returns_empty():
    ov = load_overrides(None)
    assert ov == {"sources": [], "rows": []}


def test_load_overrides_reads_sections(tmp_path):
    p = tmp_path / "ov.json"
    p.write_text(json.dumps({"sources": [{"match_source": "moneyvox"}]}), encoding="utf-8")
    ov = load_overrides(p)
    assert ov["sources"] == [{"match_source": "moneyvox"}]
    assert ov["rows"] == []


def test_present_on_map_exact_via_geo():
    payload = {"closures": [{"id": "abc", "banque": "BNP Paribas", "commune": "Lyon",
                             "lat": 45.75, "lon": 4.85, "statut": "confirmé"}]}
    cov = classify_coverage(_row(commune="Lyon", lat=45.751, lon=4.851), payload)
    assert cov["status"] == "present_on_map"
    assert cov["match_type"] == "exact"
    assert cov["pipeline_id"] == "abc"
    assert cov["pipeline_status"] == "confirmé"


def test_present_on_map_commune_when_geo_far():
    payload = {"closures": [{"id": "abc", "banque": "BNP Paribas", "commune": "Lyon",
                             "lat": 45.75, "lon": 4.85}]}
    cov = classify_coverage(_row(commune="Lyon", lat=48.85, lon=2.35), payload)
    assert cov["status"] == "present_on_map"
    assert cov["match_type"] == "commune"


def test_present_unlocated_when_closure_has_no_geo():
    payload = {"closures": [{"id": "abc", "banque": "BNP Paribas", "commune": "Lyon",
                             "lat": None, "lon": None}]}
    cov = classify_coverage(_row(commune="Lyon"), payload)
    assert cov["status"] == "present_unlocated"
    assert cov["match_type"] == "commune"


def test_present_department_via_vigilance():
    payload = {"closures": [],
               "vigilances": [{"banque": "BNP Paribas", "departement": "69"}]}
    cov = classify_coverage(_row(commune="Lyon", departement="Rhône"), payload)
    assert cov["status"] == "present_department"
    assert cov["match_type"] == "département"


def test_needs_research_when_nothing_matches():
    cov = classify_coverage(_row(commune="Lyon", departement="Rhône"), {"closures": []})
    assert cov["status"] == "needs_research"
    assert cov["match_type"] == "aucun"
    assert cov["pipeline_id"] == ""


_OV = {
    "sources": [
        {"match_source": "moneyvox", "source_reliability": "medium",
         "source_flag": "article_list_secondary"},
        {"match_source": "fichier principal v2", "require_no_url": True,
         "source_reliability": "low", "source_flag": "inherited_source_to_trace",
         "default_status_if_uncovered": "needs_research",
         "default_next_action": "Tracer la source primaire."},
    ],
    "rows": [
        {"match": {"banque": "Crédit Agricole Centre Ouest", "commune": "Reuilly"},
         "source_reliability": "high", "source_flag": "confirmed"},
    ],
}


def test_reliability_source_rule_moneyvox():
    rel = apply_reliability(_row(source="MoneyVox, 06/06/2025", url="http://x"), _OV)
    assert rel["source_reliability"] == "medium"
    assert rel["source_flag"] == "article_list_secondary"


def test_reliability_v2_requires_no_url():
    rel = apply_reliability(_row(source="Fichier principal V2", url=""), _OV)
    assert rel["source_reliability"] == "low"
    assert rel["source_flag"] == "inherited_source_to_trace"
    assert rel["_source_default_status"] == "needs_research"
    # Une ligne V2 AVEC une url ne déclenche pas la règle (require_no_url).
    rel2 = apply_reliability(_row(source="Fichier principal V2", url="http://x"), _OV)
    assert rel2["source_reliability"] == "medium"  # heuristique URL présente
    assert rel2.get("source_flag") in (None, "")


def test_reliability_row_rule_reuilly():
    rel = apply_reliability(
        _row(banque="Crédit Agricole Centre Ouest", commune="Reuilly",
             source="ICI Centre-Val de Loire", url="http://x"), _OV)
    assert rel["source_reliability"] == "high"
    assert rel["source_flag"] == "confirmed"


def test_reliability_default_heuristic():
    assert apply_reliability(_row(source="Inconnu", url="http://x"), _OV)["source_reliability"] == "medium"
    assert apply_reliability(_row(source="Inconnu", url=""), _OV)["source_reliability"] == "low"
