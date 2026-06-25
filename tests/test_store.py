# tests/test_store.py
import backend.store as store

def _closure(**kw):
    base = dict(id="abc123", banque="BNP", commune="Lyon", code_insee=None,
                departement="69", type="fermeture", date_annonce="2026-01-10",
                date_fermeture=None, statut="projet", fiabilite=3,
                lat=None, lon=None, citation="...")
    base.update(kw)
    return base

def test_init_cree_tables(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    noms = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "closures", "sources", "seen_urls", "referentiel", "controles_sirene", "vigilances",
    } <= noms

def test_upsert_puis_lecture(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    cid = store.upsert_closure(conn, _closure())
    assert cid == "abc123"
    row = conn.execute("SELECT banque, fiabilite FROM closures WHERE id=?", (cid,)).fetchone()
    assert row == ("BNP", 3)

def test_upsert_garde_fiabilite_max(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, _closure(fiabilite=2))
    store.upsert_closure(conn, _closure(fiabilite=5))
    fiab = conn.execute("SELECT fiabilite FROM closures WHERE id='abc123'").fetchone()[0]
    assert fiab == 5

def test_upsert_complete_champs_nuls(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, _closure(date_fermeture=None))
    store.upsert_closure(conn, _closure(date_fermeture="2026-06-30"))
    val = conn.execute("SELECT date_fermeture FROM closures WHERE id='abc123'").fetchone()[0]
    assert val == "2026-06-30"

def test_sources_dedupliquees(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, _closure())
    s = dict(url="http://x", titre="t", source="OF", date="2026-01-10")
    store.add_source(conn, "abc123", s)
    store.add_source(conn, "abc123", s)
    n = conn.execute("SELECT COUNT(*) FROM sources WHERE closure_id='abc123'").fetchone()[0]
    assert n == 1

def test_cache_urls(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    assert store.is_url_seen(conn, "http://a") is False
    store.mark_url_seen(conn, "http://a")
    assert store.is_url_seen(conn, "http://a") is True

def test_upsert_controle_sirene(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, _closure())
    store.upsert_controle_sirene(conn, "abc123", {
        "etat_administratif": "A", "siret": "123", "source": "SIRENE",
    })
    store.upsert_controle_sirene(conn, "abc123", {
        "etat_administratif": "F", "siret": "456", "source": "SIRENE",
    })
    row = conn.execute(
        "SELECT etat_administratif, siret, source FROM controles_sirene WHERE closure_id='abc123'"
    ).fetchone()
    assert row == ("F", "456", "SIRENE")

def test_upsert_vigilance(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    v = dict(id="v1", banque="BNP", departement="69", titre="Plan social",
             extrait="fermetures possibles", url="http://v", source="Légifrance",
             date="2026-01-10", score=2, raison="signal")
    store.upsert_vigilance(conn, v)
    store.upsert_vigilance(conn, {**v, "score": 4, "titre": "Plan social actualisé"})
    row = conn.execute("SELECT titre, score FROM vigilances WHERE id='v1'").fetchone()
    assert row == ("Plan social actualisé", 4)

def test_migration_legacy_db_ajoute_colonnes_temporelles(tmp_path):
    """init_db doit ajouter statut_temporel et date_fermeture_approx à une DB
    existante qui ne les possède pas (migration idempotente)."""
    import sqlite3
    db_path = tmp_path / "legacy.db"
    # Créer une DB legacy sans les deux nouvelles colonnes
    legacy = sqlite3.connect(str(db_path))
    legacy.execute("""CREATE TABLE closures (
        id TEXT PRIMARY KEY,
        banque TEXT NOT NULL,
        commune TEXT NOT NULL,
        code_insee TEXT,
        departement TEXT,
        type TEXT NOT NULL,
        date_annonce TEXT,
        date_fermeture TEXT,
        statut TEXT,
        fiabilite INTEGER,
        lat REAL,
        lon REAL,
        citation TEXT,
        created_at TEXT NOT NULL
    )""")
    legacy.commit()
    legacy.close()

    # init_db doit migrer la DB existante
    conn = store.init_db(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(closures)")}
    assert "statut_temporel" in cols, "statut_temporel manquant après migration"
    assert "date_fermeture_approx" in cols, "date_fermeture_approx manquant après migration"

    # upsert_closure doit fonctionner et les defaults doivent être corrects
    from datetime import datetime, timezone
    conn.execute(
        """INSERT INTO closures
           (id, banque, commune, code_insee, departement, type, date_annonce,
            date_fermeture, statut, fiabilite, lat, lon, citation,
            statut_temporel, date_fermeture_approx, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("leg1", "BNP", "Paris", None, "75", "fermeture", None, None, "projet",
         3, None, None, "x", "inconnu", 0, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT statut_temporel, date_fermeture_approx FROM closures WHERE id='leg1'"
    ).fetchone()
    assert row == ("inconnu", 0), f"Defaults incorrects: {row}"


def test_closure_persiste_statut_temporel(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    store.upsert_closure(conn, {
        "id": "abc", "banque": "BNP Paribas", "commune": "Lyon",
        "code_insee": None, "departement": "69", "type": "fermeture",
        "date_annonce": None, "date_fermeture": "2025-03-01",
        "statut": "confirmé", "fiabilite": 5, "lat": None, "lon": None,
        "citation": "x", "statut_temporel": "deja_fermee",
        "date_fermeture_approx": 1,
    })
    row = conn.execute(
        "SELECT statut_temporel, date_fermeture_approx FROM closures WHERE id='abc'"
    ).fetchone()
    assert row == ("deja_fermee", 1)
