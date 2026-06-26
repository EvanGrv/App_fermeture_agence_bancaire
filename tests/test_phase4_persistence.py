import sqlite3

import backend.store as store
from backend import export


def _closure(**kw):
    base = dict(id="loc1", banque="Société Générale", commune="Guer",
                code_insee="56075", departement="56", type="fermeture",
                date_annonce=None, date_fermeture="2026-01-15", statut="confirmé",
                fiabilite=4, lat=47.9, lon=-2.1, citation="x",
                agence_localisation="Coëtquidan", commune_originale="Coëtquidan",
                adresse="Camp de Coëtquidan")
    base.update(kw)
    return base


def test_upsert_persiste_localisation_et_adresse(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, _closure())
    row = conn.execute(
        "SELECT commune, agence_localisation, commune_originale, adresse "
        "FROM closures WHERE id='loc1'"
    ).fetchone()
    assert row == ("Guer", "Coëtquidan", "Coëtquidan", "Camp de Coëtquidan")


def test_upsert_sans_nouveaux_champs_fonctionne(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    minimal = {"id": "m1", "banque": "BNP Paribas", "commune": "Lyon",
               "code_insee": None, "departement": "69", "type": "fermeture",
               "date_annonce": None, "date_fermeture": None, "statut": "projet",
               "fiabilite": 3, "lat": None, "lon": None, "citation": "x"}
    store.upsert_closure(conn, minimal)
    row = conn.execute(
        "SELECT agence_localisation FROM closures WHERE id='m1'").fetchone()
    assert row == (None,)


def test_export_expose_localisation(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, _closure())
    cl = export.build_payload(conn)["closures"][0]
    assert cl["commune"] == "Guer"
    assert cl["agence_localisation"] == "Coëtquidan"


def test_migration_legacy_ajoute_colonnes_localisation(tmp_path):
    db_path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(str(db_path))
    legacy.execute("""CREATE TABLE closures (
        id TEXT PRIMARY KEY, banque TEXT NOT NULL, commune TEXT NOT NULL,
        code_insee TEXT, departement TEXT, type TEXT NOT NULL, date_annonce TEXT,
        date_fermeture TEXT, statut TEXT, fiabilite INTEGER, lat REAL, lon REAL,
        citation TEXT, created_at TEXT NOT NULL
    )""")
    legacy.commit()
    legacy.close()
    conn = store.init_db(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(closures)")}
    assert {"adresse", "agence_localisation", "commune_originale"} <= cols
