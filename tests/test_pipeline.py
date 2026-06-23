# tests/test_pipeline.py
import backend.store as store
from backend import pipeline

def _article(url, pertinent=True):
    if pertinent:
        return {"titre": "BNP ferme son agence", "texte": "agence fermée à Lyon",
                "url": url, "date": "2026-01-10", "source": "GN", "departement": "69"}
    return {"titre": "Météo", "texte": "soleil", "url": url, "date": "", "source": "GN",
            "departement": None}

def _extractor(article):
    return {"id": "abc123", "banque": "BNP", "commune": "Lyon", "code_insee": None,
            "departement": "69", "type": "fermeture", "date_annonce": "2026-01-10",
            "date_fermeture": None, "statut": "projet", "fiabilite": 3,
            "lat": None, "lon": None, "citation": "agence fermée à Lyon"}

def test_pipeline_complet(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    collectors = [lambda: [_article("http://1"), _article("http://2", pertinent=False)]]
    recap = pipeline.run_pipeline(
        conn, collectors,
        extractor_fn=_extractor,
        geocoder_fn=lambda commune, dept: (45.76, 4.85),
    )
    assert recap["articles"] == 2
    assert recap["filtres"] == 1   # seul l'article pertinent passe le pré-filtre
    assert recap["fermetures"] == 1
    row = conn.execute("SELECT lat, lon FROM closures WHERE id='abc123'").fetchone()
    assert row == (45.76, 4.85)

def test_pipeline_idempotent(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    collectors = [lambda: [_article("http://1")]]
    pipeline.run_pipeline(conn, collectors, _extractor, lambda c, d: (1.0, 2.0))
    recap = pipeline.run_pipeline(conn, collectors, _extractor, lambda c, d: (1.0, 2.0))
    assert recap["filtres"] == 0  # URL déjà vue -> ignorée
    n = conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0]
    assert n == 1
