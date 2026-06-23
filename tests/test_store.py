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
    assert {"closures", "sources", "seen_urls", "referentiel", "controles_sirene"} <= noms

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
