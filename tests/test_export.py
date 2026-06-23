import json
import backend.store as store
from backend import export

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
