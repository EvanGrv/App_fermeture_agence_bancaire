from datetime import datetime, timedelta, timezone

import backend.store as store
import config
from backend.extraction_cache import content_hash, extract_cached, extract_cached_with_status

_ART = {"titre": "BNP ferme", "texte": "agence fermée à Lyon"}


def _conn(tmp_path):
    return store.init_db(tmp_path / "t.db")


def test_miss_appelle_extract_et_cache_closure(tmp_path):
    conn = _conn(tmp_path)
    appels = []

    def extract_fn(art):
        appels.append(1)
        return {"id": "x", "banque": "BNP"}

    r = extract_cached(_ART, extract_fn, conn)
    assert r == {"id": "x", "banque": "BNP"}
    assert len(appels) == 1
    r2 = extract_cached(_ART, extract_fn, conn)
    assert r2 == {"id": "x", "banque": "BNP"}
    assert len(appels) == 1


def test_none_est_mis_en_cache(tmp_path):
    conn = _conn(tmp_path)
    appels = []

    def extract_fn(art):
        appels.append(1)
        return None

    assert extract_cached(_ART, extract_fn, conn) is None
    assert extract_cached(_ART, extract_fn, conn) is None
    assert len(appels) == 1, "none doit être caché : pas de second appel IA"


def test_cle_inclut_le_modele(tmp_path):
    conn = _conn(tmp_path)
    appels = []

    def extract_fn(art):
        appels.append(1)
        return None

    extract_cached(_ART, extract_fn, conn, model="claude-haiku-4-5")
    extract_cached(_ART, extract_fn, conn, model="claude-sonnet-4-6")
    assert len(appels) == 2, "modèle différent -> miss"


def test_cle_inclut_la_version(tmp_path):
    conn = _conn(tmp_path)
    appels = []

    def extract_fn(art):
        appels.append(1)
        return None

    extract_cached(_ART, extract_fn, conn, version=1)
    extract_cached(_ART, extract_fn, conn, version=2)
    assert len(appels) == 2


def test_error_reessayable_apres_retry_after(tmp_path):
    conn = _conn(tmp_path)
    appels = []
    t0 = datetime(2026, 6, 30, tzinfo=timezone.utc)

    def extract_boom(art):
        appels.append(1)
        raise RuntimeError("API 529")

    assert extract_cached(_ART, extract_boom, conn, now_fn=lambda: t0) is None
    assert len(appels) == 1
    row = store.get_extraction(conn, content_hash(_ART), config.EXTRACTION_VERSION,
                               config.ANTHROPIC_MODEL)
    assert row["status"] == "error" and row["attempts"] == 1 and row["retry_after"]
    # avant retry_after -> soft-skip (pas de rappel IA)
    assert extract_cached(_ART, extract_boom, conn, now_fn=lambda: t0) is None
    assert len(appels) == 1
    # après retry_after -> nouvel essai
    plus_tard = t0 + timedelta(minutes=config.EXTRACTION_RETRY_BASE_MIN + 1)
    assert extract_cached(_ART, extract_boom, conn, now_fn=lambda: plus_tard) is None
    assert len(appels) == 2


def test_extract_cached_with_status_signale_error_et_soft_skip(tmp_path):
    conn = _conn(tmp_path)
    t0 = datetime(2026, 6, 30, tzinfo=timezone.utc)

    def extract_boom(art):
        raise RuntimeError("API 529")

    result, status = extract_cached_with_status(_ART, extract_boom, conn, now_fn=lambda: t0)
    assert result is None
    assert status == "error"
    result, status = extract_cached_with_status(_ART, extract_boom, conn, now_fn=lambda: t0)
    assert result is None
    assert status == "error_skip"


def test_error_bloque_apres_max_attempts(tmp_path):
    conn = _conn(tmp_path)
    futur = datetime(2030, 1, 1, tzinfo=timezone.utc)
    store.upsert_extraction(conn, {
        "content_hash": content_hash(_ART), "extraction_version": config.EXTRACTION_VERSION,
        "model": config.ANTHROPIC_MODEL, "status": "error", "result_json": None,
        "error_type": "X", "attempts": config.EXTRACTION_MAX_ATTEMPTS, "retry_after": None,
        "created_at": "2026-06-30T00:00:00+00:00", "updated_at": "2026-06-30T00:00:00+00:00"})
    appels = []

    def extract_fn(art):
        appels.append(1)
        return None

    assert extract_cached(_ART, extract_fn, conn, now_fn=lambda: futur) is None
    assert len(appels) == 0, "max_attempts atteint -> soft-skip même retry_after passé"
