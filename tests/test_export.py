import json
import csv
import backend.store as store
from backend import export


def test_export_expose_statut_temporel(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, {
        "id": "z", "banque": "La Banque Postale", "commune": "Tulle",
        "code_insee": "19272", "departement": "19", "type": "fermeture",
        "date_annonce": None, "date_fermeture": "2025-09-01", "statut": "confirmé",
        "fiabilite": 4, "lat": 45.2, "lon": 1.7, "citation": "x",
        "statut_temporel": "deja_fermee", "date_fermeture_approx": 0,
    })
    payload = export.build_payload(conn)
    cl = payload["closures"][0]
    assert cl["statut_temporel"] == "deja_fermee"
    assert cl["date_fermeture_approx"] == 0


def _seed(conn):
    c = dict(id="abc123", banque="BNP", commune="Lyon", code_insee="69003",
             departement="69", type="fermeture", date_annonce="2026-01-10",
             date_fermeture="2026-06-30", statut="projet", fiabilite=3,
             lat=45.76, lon=4.85, citation="...")
    store.upsert_closure(conn, c)
    store.add_source(conn, "abc123",
                     dict(url="http://x", titre="t", source="OF", date="2026-01-10"))
    store.upsert_controle_sirene(conn, "abc123", {
        "etat_administratif": "F", "siret": "12345678900010", "source": "SIRENE",
    })
    store.upsert_vigilance(conn, dict(
        id="v1", banque="BNP", departement="69", titre="Accord PSE",
        extrait="restructuration et fermeture agences", url="http://v",
        source="Légifrance", date="2026-02-01", score=4, raison="signal faible",
    ))

def test_build_payload(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    _seed(conn)
    store.upsert_referentiel(conn, dict(
        osm_id="node/1", banque="BNP", commune="Lyon", code_postal="69003",
        departement="69", lat=45.76, lon=4.85, source="OSM",
    ))
    store.upsert_referentiel(conn, dict(
        osm_id="node/2", banque="LCL", commune="Lyon", code_postal="69006",
        departement="69", lat=45.77, lon=4.84, source="OSM",
    ))
    p = export.build_payload(conn)
    assert "generated_at" in p
    assert p["departements"]["69"]["count"] == 1
    assert p["departements"]["69"]["total_agences"] == 2
    assert p["departements"]["69"]["nom"] == "Rhône"
    cl = p["closures"][0]
    assert cl["banque"] == "BNP"
    assert cl["sources"][0]["url"] == "http://x"
    assert cl["controle_sirene"]["etat_administratif"] == "F"
    assert p["vigilances"][0]["titre"] == "Accord PSE"
    # plans nationaux non nominatifs présents et distincts des closures
    assert any(pl["banque"] == "Société Générale" for pl in p["plans"])

def test_export_json_ecrit_fichier(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    _seed(conn)
    out = tmp_path / "sub" / "data.json"
    export.export_json(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["closures"]) == 1

def test_export_fermetures_csv_excel(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    _seed(conn)
    out = tmp_path / "fermetures.csv"

    export.export_fermetures_csv(conn, out)

    rows = list(csv.DictReader(out.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0]["Banque"] == "BNP"
    assert rows[0]["Commune"] == "Lyon"
    assert rows[0]["Département"] == "69"
    assert rows[0]["Région"] == "Auvergne-Rhône-Alpes"
    assert rows[0]["Source"] == "OF"
    assert rows[0]["URL"] == "http://x"
    assert rows[0]["À vérifier"] == "oui"
    # statut_temporel absent dans _seed → "Inconnu"
    assert rows[0]["Temporalité"] == "Inconnu"


def test_export_csv_temporalite_mapping(tmp_path):
    """Vérifie le mapping statut_temporel → colonne Temporalité du CSV."""
    conn = store.init_db(tmp_path / "t.db")
    base = dict(banque="BNP", commune="Lyon", code_insee="69003", departement="69",
                type="fermeture", date_annonce=None, date_fermeture="2026-06-30",
                statut="confirmé", fiabilite=4, lat=45.76, lon=4.85, citation="c")
    store.upsert_closure(conn, {**base, "id": "d1", "statut_temporel": "deja_fermee", "date_fermeture_approx": 0})
    store.upsert_closure(conn, {**base, "id": "d2", "statut_temporel": "a_venir", "date_fermeture_approx": 0})
    store.upsert_closure(conn, {**base, "id": "d3", "statut_temporel": None, "date_fermeture_approx": None})
    out = tmp_path / "fermetures.csv"
    export.export_fermetures_csv(conn, out)
    # Use a fresh read keyed by row order
    all_rows = list(csv.DictReader(out.read_text(encoding="utf-8-sig").splitlines()))
    temp_vals = {r["Temporalité"] for r in all_rows}
    assert "Déjà fermée" in temp_vals
    assert "À venir" in temp_vals
    assert "Inconnu" in temp_vals
