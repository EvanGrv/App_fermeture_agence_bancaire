"""Tests pour backend/fulltext.py — fetch_article (SQLite, cache-first) + fetch_text."""
import backend.store as store
from backend.fulltext import FetchResult, fetch_article, fetch_text

_ARTICLE_HTML = """\
<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<title>Fermeture agence Crédit Agricole à Limoges</title></head>
<body><main><article>
<h1>Le Crédit Agricole ferme son agence du centre-ville de Limoges</h1>
<p>Le Crédit Agricole Centre Ouest a annoncé la fermeture définitive de son agence
rue Jean-Jaurès à Limoges, prévue pour le 30 septembre 2026. Cette décision s'inscrit
dans le plan de rationalisation du réseau bancaire régional, qui vise à concentrer les
services sur des agences plus grandes et mieux équipées pour la clientèle locale.</p>
<p>Selon le directeur régional, les clients seront redirigés vers l'agence de la place
Denis-Dussoubs, distante de seulement 400 mètres, avec des conseillers dédiés.</p>
</article></main></body></html>
"""


def _fetch_ok(url):
    return FetchResult(text=_ARTICLE_HTML, url=url)


def test_fetch_article_upsert_avec_hash_et_metadonnees(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    row = fetch_article("https://ex.com/a", fetch=_fetch_ok, conn=conn)
    assert row["fetch_status"] == "ok"
    assert "Crédit Agricole" in row["fulltext"]
    assert row["fulltext_hash"] and len(row["fulltext_hash"]) == 16
    assert row["source_domain"] == "ex.com"
    assert store.get_article(conn, "https://ex.com/a")["fetch_status"] == "ok"


def test_fetch_article_cache_first_ne_refetch_pas(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    appels = []

    def fetch_spy(url):
        appels.append(url)
        return FetchResult(text=_ARTICLE_HTML, url=url)

    fetch_article("https://ex.com/cache", fetch=fetch_spy, conn=conn)
    fetch_article("https://ex.com/cache", fetch=fetch_spy, conn=conn)
    assert len(appels) == 1, f"fetch appelé {len(appels)} fois au lieu de 1"


def test_fetch_text_renvoie_le_corps(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    txt = fetch_text("https://ex.com/t", fetch=_fetch_ok, conn=conn)
    assert isinstance(txt, str) and "Crédit Agricole" in txt


def test_fetch_text_accepte_cache_dir_deprecie(tmp_path):
    """cache_dir est accepté (ignoré) pour compat ascendante."""
    conn = store.init_db(tmp_path / "t.db")
    txt = fetch_text("https://ex.com/cd", fetch=_fetch_ok, cache_dir=tmp_path, conn=conn)
    assert "Crédit Agricole" in txt


def test_fetch_article_accepte_fetch_str(tmp_path):
    """Un fetch renvoyant une simple chaîne HTML est accepté."""
    conn = store.init_db(tmp_path / "t.db")
    row = fetch_article("https://ex.com/str", fetch=lambda u: _ARTICLE_HTML, conn=conn)
    assert row["fetch_status"] == "ok"
    assert "Crédit Agricole" in row["fulltext"]
    assert row["final_url"] == "https://ex.com/str"  # final_url retombe sur l'url demandée


def test_fetch_article_accepte_fetch_dict(tmp_path):
    """Un fetch renvoyant un dict {'text','url'} est accepté."""
    conn = store.init_db(tmp_path / "t.db")
    row = fetch_article(
        "https://ex.com/d",
        fetch=lambda u: {"text": _ARTICLE_HTML, "url": "https://ex.com/d/final"},
        conn=conn,
    )
    assert row["fetch_status"] == "ok"
    assert row["final_url"] == "https://ex.com/d/final"


def test_fetch_article_echec_status_error_refetchable(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    appels = []

    def fetch_raises(url):
        appels.append(url)
        raise RuntimeError("Connexion refusée")

    row = fetch_article("https://ex.com/ko", fetch=fetch_raises, conn=conn)
    assert row["fetch_status"] == "error"
    assert row["fulltext"] == ""
    # cache-first ne court-circuite QUE 'ok' -> un 2e appel re-tente le fetch
    fetch_article("https://ex.com/ko", fetch=fetch_raises, conn=conn)
    assert len(appels) == 2
