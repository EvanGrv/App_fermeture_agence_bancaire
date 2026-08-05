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


def test_export_expose_impact_postal(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, {
        "id": "lbp", "banque": "La Banque Postale", "commune": "Nomexy",
        "code_insee": "88327", "departement": "88", "type": "fermeture",
        "date_annonce": "2026-06-01", "date_fermeture": "2026-07-01",
        "statut": "confirmé", "fiabilite": 5, "lat": 48.3, "lon": 6.4,
        "citation": "Transformation du bureau", "service_impact": "conversion_ap",
        "point_postal_avant": "Bureau de Poste",
        "point_postal_apres": "Agence postale communale",
        "postal_point_id": "12345A", "evidence_level": "officiel",
    })
    closure = export.build_payload(conn)["closures"][0]
    assert closure["service_impact"] == "conversion_ap"
    assert closure["point_postal_apres"] == "Agence postale communale"


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
    assert "BNP Paribas" in p["enseignes"]
    assert p["departements"]["69"]["count"] == 1
    assert p["departements"]["69"]["total_agences"] == 2
    assert p["departements"]["69"]["nom"] == "Rhône"
    cl = p["closures"][0]
    assert cl["banque"] == "BNP Paribas"
    assert cl["sources"][0]["url"] == "http://x"
    assert cl["controle_sirene"]["etat_administratif"] == "F"
    assert p["vigilances"][0]["titre"] == "Accord PSE"
    # plans nationaux non nominatifs présents et distincts des closures
    assert any(pl["banque"] == "Société Générale" for pl in p["plans"])


def test_build_payload_reconcilie_historique_avant_export(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    source_url = "https://ici.fr/reuilly"
    store.upsert_closure(conn, {
        "id": "reuilly", "banque": "Crédit Agricole", "commune": "Reuilly",
        "code_insee": "36171", "departement": "36", "type": "fermeture",
        "date_annonce": "2026-01-23", "date_fermeture": "2026-06-26",
        "statut": "confirmé", "fiabilite": 5, "lat": 47.08, "lon": 2.03,
        "citation": "L'agence de Reuilly ferme.",
    })
    store.add_source(conn, "reuilly", {
        "url": source_url, "titre": "Reuilly ferme", "source": "ICI",
        "date": "2026-01-23",
    })
    store.upsert_closure_unlocated(conn, {
        "id": "u-reuilly", "banque": "Crédit Agricole", "commune": "Reuilly",
        "departement": "36", "type": "fermeture", "statut": "confirmé",
        "fiabilite": 4, "citation": "x", "url": source_url,
        "titre": "Reuilly ferme", "source": "ICI", "date": "2026-01-23",
        "raison": "commune non géocodée",
    })
    store.upsert_vigilance(conn, {
        "id": "v-reuilly", "banque": "Crédit Agricole", "departement": "36",
        "titre": "Crédit Agricole Reuilly fermeture agence", "extrait": "",
        "url": source_url, "source": "ICI", "date": "2026-01-23",
        "score": 5, "raison": "signal",
    })

    payload = export.build_payload(conn)

    assert [closure["id"] for closure in payload["closures"]] == ["reuilly"]
    assert payload["closures_unlocated"] == []
    assert payload["vigilances"] == []
    assert payload["department_estimates"]["36"]["estimated_count"] == 1

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
    assert rows[0]["Banque"] == "BNP Paribas"
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


def test_build_payload_source_tier(tmp_path):
    """Each source in build_payload's output carries a 'tier' field and original keys."""
    conn = store.init_db(tmp_path / "t.db")
    _seed(conn)
    p = export.build_payload(conn)
    cl = p["closures"][0]
    assert cl["sources"], "fixture must have at least one source"
    src = cl["sources"][0]
    assert "tier" in src, "'tier' key missing from source dict"
    assert src["tier"] in {"A", "B", "C", "D", "E"}, f"unexpected tier value: {src['tier']!r}"
    # Original source keys must still be present (Fix D: regression guard)
    for key in ("url", "titre", "source", "date"):
        assert key in src, f"original source key '{key}' missing from source dict"


def test_build_payload_department_estimates(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, {
        "id": "c1", "banque": "BNP Paribas", "commune": "Lyon",
        "code_insee": "69123", "departement": "69", "type": "fermeture",
        "date_annonce": None, "date_fermeture": None, "statut": "projet",
        "fiabilite": 3, "lat": 45.76, "lon": 4.85, "citation": "x",
    })
    store.upsert_vigilance(conn, dict(
        id="v-local", banque="Crédit Agricole", departement="69",
        titre="L'agence du Crédit Agricole de Tarare va fermer",
        extrait="", url="http://local", source="PQR", date="2026-01-01",
        score=3, raison="article pertinent sans fermeture publiable",
    ))
    store.upsert_vigilance(conn, dict(
        id="v-vague", banque="Crédit Agricole", departement="69",
        titre="10 agences ferment dans le Rhône",
        extrait="", url="http://vague", source="PQR", date="2026-01-01",
        score=3, raison="plan vague",
    ))

    payload = export.build_payload(conn)

    estimate = payload["department_estimates"]["69"]
    assert estimate["precise_count"] == 1
    assert estimate["unlocated_count"] == 1
    assert estimate["estimated_count"] == 2
    assert estimate["signals"][0]["commune"] == "Tarare"
    assert payload["departements"]["69"]["estimated_count"] == 2


def test_build_payload_expose_tiers_multiniveaux(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, {
        "id": "c1", "banque": "BNP Paribas", "commune": "Lyon",
        "code_insee": "69123", "departement": "69", "type": "fermeture",
        "date_annonce": None, "date_fermeture": None, "statut": "projet",
        "fiabilite": 3, "lat": 45.76, "lon": 4.85, "citation": "x",
    })
    store.upsert_closure_unlocated(conn, {
        "id": "u1", "banque": "BNP Paribas", "commune": "Tarare",
        "departement": "69", "type": "fermeture", "statut": "projet",
        "fiabilite": 3, "citation": "preuve", "url": "http://u",
        "titre": "Agence BNP", "source": "PQR", "date": "2026-01-01",
        "raison": "non géocodée",
    })
    store.upsert_department_signal(conn, {
        "id": "d1", "banque": "BNP Paribas", "departement": "69",
        "count": 2, "communes_mentioned": "Tarare, Lyon", "confidence": 0.7,
        "evidence": "2 agences dans le Rhône", "url": "http://d",
        "titre": "Plan Rhône", "source": "PQR", "date": "2026-01-01",
    })

    payload = export.build_payload(conn)

    assert payload["closures_unlocated"][0]["commune"] == "Tarare"
    assert payload["department_signals"][0]["count"] == 2
    estimate = payload["department_estimates"]["69"]
    assert estimate["precise_count"] == 1
    assert estimate["unlocated_count"] == 1
    assert estimate["department_signal_count"] == 2
    assert estimate["estimated_count"] == 4


def test_department_estimate_exclut_les_rejets_de_la_quarantaine(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    base = {
        "banque": "La Banque Postale", "commune": "Paray-Vieille-Poste",
        "departement": "91", "type": "fermeture", "statut": "projet",
        "fiabilite": 3, "citation": "x", "source": "PQR", "date": "2026-01-01",
    }
    for ident, reason in (
        ("u-window", "hors fenêtre temporelle"),
        ("u-temp", "garde entrée/sortie: fermeture postale temporaire ou circonstancielle"),
        ("u-dep", "garde entrée/sortie: département source 44 incompatible avec la sortie 91"),
    ):
        store.upsert_closure_unlocated(conn, {
            **base, "id": ident, "url": f"http://{ident}", "raison": reason,
        })

    payload = export.build_payload(conn)

    assert "91" not in payload["department_estimates"]
    assert payload["departements"]["91"]["unlocated_count"] == 0
    assert payload["departements"]["91"]["estimated_count"] == 0


def test_department_estimate_compte_seulement_les_vrais_xy(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, {
        "id": "c-no-xy", "banque": "BNP Paribas", "commune": "Melun",
        "code_insee": "77288", "departement": "77", "type": "fermeture",
        "date_annonce": None, "date_fermeture": None,
        "statut": "projet", "fiabilite": 3, "citation": "x",
        "lat": None, "lon": None,
    })

    estimate = export.build_payload(conn)["department_estimates"]["77"]

    assert estimate["precise_count"] == 0
    assert estimate["estimated_count"] == 0


def test_department_estimate_normalise_les_noms_departementaux(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure_unlocated(conn, {
        "id": "u-name", "banque": "Crédit Agricole", "commune": "Reuilly",
        "departement": "Indre", "type": "fermeture", "statut": "confirmé",
        "fiabilite": 4, "citation": "x", "url": "http://u-name",
        "titre": "Fermeture à Reuilly", "source": "PQR", "date": "2026-01-01",
        "raison": "commune non géocodée",
    })

    payload = export.build_payload(conn)

    assert payload["closures_unlocated"][0]["departement"] == "36"
    assert payload["department_estimates"]["36"]["unlocated_count"] == 1
