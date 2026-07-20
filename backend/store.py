# backend/store.py
import re
import sqlite3
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS closures (
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
    statut_temporel TEXT DEFAULT 'inconnu',
    date_fermeture_approx INTEGER DEFAULT 0,
    adresse TEXT,
    agence_localisation TEXT,
    commune_originale TEXT,
    service_impact TEXT,
    point_postal_avant TEXT,
    point_postal_apres TEXT,
    postal_point_id TEXT,
    evidence_level TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    closure_id TEXT NOT NULL REFERENCES closures(id),
    url TEXT NOT NULL,
    titre TEXT,
    source TEXT,
    date TEXT,
    UNIQUE(closure_id, url)
);
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS referentiel (
    osm_id TEXT PRIMARY KEY,
    banque TEXT,
    commune TEXT,
    code_postal TEXT,
    departement TEXT,
    lat REAL,
    lon REAL,
    source TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS controles_sirene (
    closure_id TEXT PRIMARY KEY REFERENCES closures(id),
    etat_administratif TEXT,
    siret TEXT,
    source TEXT,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vigilances (
    id TEXT PRIMARY KEY,
    banque TEXT,
    departement TEXT,
    titre TEXT,
    extrait TEXT,
    url TEXT,
    source TEXT,
    date TEXT,
    score INTEGER,
    raison TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(url)
);
CREATE TABLE IF NOT EXISTS vigilance_reviews (
    id TEXT PRIMARY KEY,
    reviewed_at TEXT NOT NULL,
    review_status TEXT,
    queries_tried INTEGER DEFAULT 0,
    new_urls_found INTEGER DEFAULT 0,
    closures_created INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS closures_unlocated (
    id TEXT PRIMARY KEY,
    banque TEXT,
    commune TEXT,
    departement TEXT,
    type TEXT,
    date_fermeture TEXT,
    statut TEXT,
    statut_temporel TEXT,
    fiabilite INTEGER,
    citation TEXT,
    url TEXT,
    titre TEXT,
    source TEXT,
    date TEXT,
    raison TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(url, banque, commune)
);
CREATE TABLE IF NOT EXISTS department_signals (
    id TEXT PRIMARY KEY,
    banque TEXT,
    departement TEXT,
    count INTEGER,
    communes_mentioned TEXT,
    confidence REAL,
    evidence TEXT,
    url TEXT,
    titre TEXT,
    source TEXT,
    date TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(url, banque, departement)
);
CREATE TABLE IF NOT EXISTS vague_signals (
    id TEXT PRIMARY KEY,
    banque TEXT,
    scope TEXT,
    count INTEGER,
    confidence REAL,
    evidence TEXT,
    url TEXT,
    titre TEXT,
    source TEXT,
    date TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(url, banque, scope)
);
CREATE TABLE IF NOT EXISTS articles (
    raw_url        TEXT PRIMARY KEY,
    final_url      TEXT,
    canonical_url  TEXT,
    title          TEXT,
    source_domain  TEXT,
    published_at   TEXT,
    fetched_at     TEXT NOT NULL,
    fulltext       TEXT,
    fulltext_hash  TEXT,
    fetch_status   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extractions (
    content_hash       TEXT NOT NULL,
    extraction_version INTEGER NOT NULL,
    model              TEXT NOT NULL,
    status             TEXT NOT NULL,
    result_json        TEXT,
    error_type         TEXT,
    attempts           INTEGER NOT NULL DEFAULT 0,
    retry_after        TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    PRIMARY KEY (content_hash, extraction_version, model)
);
CREATE TABLE IF NOT EXISTS postal_syncs (
    revision TEXT PRIMARY KEY,
    observed_at TEXT NOT NULL,
    point_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS postal_points (
    point_id TEXT PRIMARY KEY,
    label TEXT,
    characteristic TEXT,
    address TEXT,
    postal_code TEXT,
    locality TEXT,
    code_insee TEXT,
    departement TEXT,
    lat REAL,
    lon REAL,
    active INTEGER NOT NULL DEFAULT 1,
    missing_revisions INTEGER NOT NULL DEFAULT 0,
    first_seen_revision TEXT NOT NULL,
    last_seen_revision TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS postal_point_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    point_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    label TEXT,
    characteristic TEXT,
    address TEXT,
    postal_code TEXT,
    locality TEXT,
    code_insee TEXT,
    departement TEXT,
    lat REAL,
    lon REAL,
    active INTEGER NOT NULL,
    UNIQUE(point_id, revision)
);
CREATE TABLE IF NOT EXISTS pipeline_migrations (
    key TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


def _ensure_closures_columns(conn: sqlite3.Connection) -> None:
    """Idempotent migration: add temporal columns to a pre-existing closures table."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(closures)")}
    if "statut_temporel" not in existing:
        conn.execute(
            "ALTER TABLE closures ADD COLUMN statut_temporel TEXT DEFAULT 'inconnu'"
        )
    if "date_fermeture_approx" not in existing:
        conn.execute(
            "ALTER TABLE closures ADD COLUMN date_fermeture_approx INTEGER DEFAULT 0"
        )
    for col in (
        "adresse", "agence_localisation", "commune_originale", "service_impact",
        "point_postal_avant", "point_postal_apres", "postal_point_id", "evidence_level",
    ):
        if col not in existing:
            conn.execute(f"ALTER TABLE closures ADD COLUMN {col} TEXT")


def init_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    _ensure_closures_columns(conn)
    conn.commit()
    return conn


_ARTICLE_COLS = ["raw_url", "final_url", "canonical_url", "title", "source_domain",
                 "published_at", "fetched_at", "fulltext", "fulltext_hash", "fetch_status"]
_EXTRACTION_COLS = ["content_hash", "extraction_version", "model", "status",
                    "result_json", "error_type", "attempts", "retry_after",
                    "created_at", "updated_at"]
_UNLOCATED_COLS = ["id", "banque", "commune", "departement", "type",
                   "date_fermeture", "statut", "statut_temporel", "fiabilite",
                   "citation", "url", "titre", "source", "date", "raison", "created_at"]
_DEPT_SIGNAL_COLS = ["id", "banque", "departement", "count", "communes_mentioned",
                     "confidence", "evidence", "url", "titre", "source", "date",
                     "created_at"]
_VAGUE_SIGNAL_COLS = ["id", "banque", "scope", "count", "confidence", "evidence",
                      "url", "titre", "source", "date", "created_at"]


def upsert_article(conn: sqlite3.Connection, article: dict) -> None:
    cols = ",".join(_ARTICLE_COLS)
    placeholders = ",".join(f":{c}" for c in _ARTICLE_COLS)
    updates = ",".join(f"{c}=excluded.{c}" for c in _ARTICLE_COLS if c != "raw_url")
    conn.execute(
        f"INSERT INTO articles ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(raw_url) DO UPDATE SET {updates}",
        {c: article.get(c) for c in _ARTICLE_COLS},
    )
    conn.commit()


def get_article(conn: sqlite3.Connection, raw_url: str) -> dict | None:
    row = conn.execute(
        f"SELECT {','.join(_ARTICLE_COLS)} FROM articles WHERE raw_url=?", (raw_url,)
    ).fetchone()
    return dict(zip(_ARTICLE_COLS, row)) if row else None


def upsert_extraction(conn: sqlite3.Connection, row: dict) -> None:
    cols = ",".join(_EXTRACTION_COLS)
    placeholders = ",".join(f":{c}" for c in _EXTRACTION_COLS)
    key = ("content_hash", "extraction_version", "model")
    updates = ",".join(f"{c}=excluded.{c}" for c in _EXTRACTION_COLS if c not in key)
    conn.execute(
        f"INSERT INTO extractions ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(content_hash, extraction_version, model) DO UPDATE SET {updates}",
        {c: row.get(c) for c in _EXTRACTION_COLS},
    )
    conn.commit()


def get_extraction(conn: sqlite3.Connection, content_hash: str,
                   extraction_version: int, model: str) -> dict | None:
    row = conn.execute(
        f"SELECT {','.join(_EXTRACTION_COLS)} FROM extractions "
        "WHERE content_hash=? AND extraction_version=? AND model=?",
        (content_hash, extraction_version, model),
    ).fetchone()
    return dict(zip(_EXTRACTION_COLS, row)) if row else None


def upsert_closure(conn: sqlite3.Connection, closure: dict) -> str:
    existing = conn.execute(
        "SELECT fiabilite, code_insee, date_fermeture, lat, lon, "
        "date_fermeture_approx FROM closures WHERE id=?",
        (closure["id"],),
    ).fetchone()
    if existing is None:
        conn.execute(
            """INSERT INTO closures
            (id, banque, commune, code_insee, departement, type, date_annonce,
             date_fermeture, statut, fiabilite, lat, lon, citation,
             statut_temporel, date_fermeture_approx,
             adresse, agence_localisation, commune_originale, service_impact,
             point_postal_avant, point_postal_apres, postal_point_id,
             evidence_level, created_at)
            VALUES (:id,:banque,:commune,:code_insee,:departement,:type,:date_annonce,
                    :date_fermeture,:statut,:fiabilite,:lat,:lon,:citation,
                    :statut_temporel,:date_fermeture_approx,
                    :adresse,:agence_localisation,:commune_originale,:service_impact,
                    :point_postal_avant,:point_postal_apres,:postal_point_id,
                    :evidence_level,:created_at)""",
            {
                "statut_temporel": "inconnu",
                "date_fermeture_approx": 0,
                "adresse": None,
                "agence_localisation": None,
                "commune_originale": None,
                "service_impact": None,
                "point_postal_avant": None,
                "point_postal_apres": None,
                "postal_point_id": None,
                "evidence_level": None,
                **closure,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    else:
        fiab_max = max(existing[0] or 0, closure.get("fiabilite") or 0)
        incoming_date = closure.get("date_fermeture")
        if existing[2] is not None:
            date_approx = existing[5] or 0
        elif incoming_date is not None:
            date_approx = closure.get("date_fermeture_approx") or 0
        else:
            date_approx = max(
                existing[5] or 0, closure.get("date_fermeture_approx") or 0
            )
        conn.execute(
            """UPDATE closures SET
                fiabilite=?,
                code_insee=COALESCE(code_insee, ?),
                date_annonce=COALESCE(date_annonce, ?),
                date_fermeture=COALESCE(date_fermeture, ?),
                statut=CASE WHEN ?='confirmé' THEN 'confirmé' ELSE statut END,
                lat=COALESCE(lat, ?),
                lon=COALESCE(lon, ?),
                citation=COALESCE(citation, ?),
                statut_temporel=COALESCE(?, statut_temporel),
                date_fermeture_approx=?,
                adresse=COALESCE(adresse, ?),
                agence_localisation=COALESCE(agence_localisation, ?),
                commune_originale=COALESCE(commune_originale, ?),
                service_impact=COALESCE(service_impact, ?),
                point_postal_avant=COALESCE(point_postal_avant, ?),
                point_postal_apres=COALESCE(point_postal_apres, ?),
                postal_point_id=COALESCE(postal_point_id, ?),
                evidence_level=COALESCE(evidence_level, ?)
               WHERE id=?""",
            (fiab_max, closure.get("code_insee"), closure.get("date_annonce"),
             closure.get("date_fermeture"), closure.get("statut"),
             closure.get("lat"), closure.get("lon"), closure.get("citation"),
             closure.get("statut_temporel"), date_approx,
             closure.get("adresse"), closure.get("agence_localisation"),
             closure.get("commune_originale"), closure.get("service_impact"),
             closure.get("point_postal_avant"), closure.get("point_postal_apres"),
             closure.get("postal_point_id"), closure.get("evidence_level"),
             closure["id"]),
        )
    conn.commit()
    return closure["id"]


def add_source(conn: sqlite3.Connection, closure_id: str, source: dict) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO sources (closure_id, url, titre, source, date)
           VALUES (?,?,?,?,?)""",
        (closure_id, source["url"], source.get("titre"),
         source.get("source"), source.get("date")),
    )
    conn.commit()


def is_url_seen(conn: sqlite3.Connection, url: str) -> bool:
    return conn.execute("SELECT 1 FROM seen_urls WHERE url=?", (url,)).fetchone() is not None


def mark_url_seen(conn: sqlite3.Connection, url: str) -> None:
    conn.execute("INSERT OR IGNORE INTO seen_urls (url) VALUES (?)", (url,))
    conn.commit()


def requeue_postal_articles(conn: sqlite3.Connection, migration_key: str) -> int:
    """Remet une fois les anciens articles postaux dans la file d'extraction."""
    if conn.execute(
        "SELECT 1 FROM pipeline_migrations WHERE key=?", (migration_key,)
    ).fetchone():
        return 0
    rows = conn.execute(
        """SELECT articles.raw_url FROM articles
           JOIN seen_urls ON seen_urls.url=articles.raw_url
           WHERE lower(COALESCE(title, '') || ' ' || COALESCE(fulltext, ''))
                 LIKE '%bureau de poste%'
              OR lower(COALESCE(title, '') || ' ' || COALESCE(fulltext, ''))
                 LIKE '%banque postale%'
              OR lower(COALESCE(title, '') || ' ' || COALESCE(fulltext, ''))
                 LIKE '%agence postale communale%'
              OR lower(COALESCE(title, '') || ' ' || COALESCE(fulltext, ''))
                 LIKE '%relais poste%'"""
    ).fetchall()
    urls = [(row[0],) for row in rows if row[0]]
    if urls:
        conn.executemany("DELETE FROM seen_urls WHERE url=?", urls)
        conn.executemany(
            "DELETE FROM vigilance_reviews WHERE id IN "
            "(SELECT id FROM vigilances WHERE url=?)",
            urls,
        )
    conn.execute(
        "INSERT INTO pipeline_migrations (key, applied_at) VALUES (?, ?)",
        (migration_key, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return len(urls)


_POSTAL_POINT_COLS = [
    "point_id", "label", "characteristic", "address", "postal_code", "locality",
    "code_insee", "departement", "lat", "lon", "active", "missing_revisions",
    "first_seen_revision", "last_seen_revision", "updated_at",
]


def postal_revision_seen(conn: sqlite3.Connection, revision: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM postal_syncs WHERE revision=?", (revision,)
    ).fetchone() is not None


def postal_points(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(f"SELECT {','.join(_POSTAL_POINT_COLS)} FROM postal_points").fetchall()
    return {row[0]: dict(zip(_POSTAL_POINT_COLS, row)) for row in rows}


def save_postal_point(conn: sqlite3.Connection, point: dict) -> None:
    placeholders = ",".join(f":{col}" for col in _POSTAL_POINT_COLS)
    updates = ",".join(
        f"{col}=excluded.{col}" for col in _POSTAL_POINT_COLS
        if col not in ("point_id", "first_seen_revision")
    )
    conn.execute(
        f"INSERT INTO postal_points ({','.join(_POSTAL_POINT_COLS)}) "
        f"VALUES ({placeholders}) ON CONFLICT(point_id) DO UPDATE SET {updates}",
        {col: point.get(col) for col in _POSTAL_POINT_COLS},
    )


def add_postal_point_history(conn: sqlite3.Connection, point: dict, revision: str,
                             observed_at: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO postal_point_history
           (point_id, revision, observed_at, label, characteristic, address,
            postal_code, locality, code_insee, departement, lat, lon, active)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (point.get("point_id"), revision, observed_at, point.get("label"),
         point.get("characteristic"), point.get("address"), point.get("postal_code"),
         point.get("locality"), point.get("code_insee"), point.get("departement"),
         point.get("lat"), point.get("lon"), point.get("active", 1)),
    )


def finish_postal_sync(conn: sqlite3.Connection, revision: str, observed_at: str,
                       point_count: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO postal_syncs (revision, observed_at, point_count) VALUES (?,?,?)",
        (revision, observed_at, point_count),
    )
    conn.commit()


def upsert_referentiel(conn: sqlite3.Connection, branche: dict) -> str:
    conn.execute(
        """INSERT INTO referentiel
           (osm_id, banque, commune, code_postal, departement, lat, lon, source, created_at)
           VALUES (:osm_id,:banque,:commune,:code_postal,:departement,:lat,:lon,:source,:created_at)
           ON CONFLICT(osm_id) DO UPDATE SET
             banque=excluded.banque,
             commune=excluded.commune,
             code_postal=excluded.code_postal,
             departement=excluded.departement,
             lat=excluded.lat,
             lon=excluded.lon,
             source=excluded.source""",
        {**branche, "created_at": datetime.now(timezone.utc).isoformat()},
    )
    conn.commit()
    return branche["osm_id"]


def upsert_controle_sirene(conn: sqlite3.Connection, closure_id: str, controle: dict) -> None:
    conn.execute(
        """INSERT INTO controles_sirene
           (closure_id, etat_administratif, siret, source, checked_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(closure_id) DO UPDATE SET
             etat_administratif=excluded.etat_administratif,
             siret=excluded.siret,
             source=excluded.source,
             checked_at=excluded.checked_at""",
        (
            closure_id,
            controle.get("etat_administratif"),
            controle.get("siret"),
            controle.get("source", "SIRENE"),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def upsert_vigilance(conn: sqlite3.Connection, vigilance: dict) -> str:
    conn.execute(
        """INSERT INTO vigilances
           (id, banque, departement, titre, extrait, url, source, date, score, raison, created_at)
           VALUES (:id,:banque,:departement,:titre,:extrait,:url,:source,:date,:score,:raison,:created_at)
           ON CONFLICT(id) DO UPDATE SET
             banque=COALESCE(excluded.banque, banque),
             departement=COALESCE(excluded.departement, departement),
             titre=excluded.titre,
             extrait=excluded.extrait,
             source=excluded.source,
             date=excluded.date,
             score=MAX(score, excluded.score),
             raison=excluded.raison""",
        {**vigilance, "created_at": datetime.now(timezone.utc).isoformat()},
    )
    conn.commit()
    return vigilance["id"]


def _insert_update(conn: sqlite3.Connection, table: str, cols: list[str],
                   row: dict, key_cols: tuple[str, ...] = ("id",)) -> str:
    placeholders = ",".join(f":{c}" for c in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in key_cols)
    conn.execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        {
            **{c: None for c in cols},
            **row,
            "created_at": row.get("created_at") or datetime.now(timezone.utc).isoformat(),
        },
    )
    conn.commit()
    return row["id"]


def upsert_closure_unlocated(conn: sqlite3.Connection, closure: dict) -> str:
    return _insert_update(conn, "closures_unlocated", _UNLOCATED_COLS, closure)


def upsert_department_signal(conn: sqlite3.Connection, signal: dict) -> str:
    return _insert_update(conn, "department_signals", _DEPT_SIGNAL_COLS, signal)


def upsert_vague_signal(conn: sqlite3.Connection, signal: dict) -> str:
    return _insert_update(conn, "vague_signals", _VAGUE_SIGNAL_COLS, signal)


_VIGILANCE_SELECT_COLS = ["id", "banque", "departement", "titre", "extrait",
                          "url", "source", "date", "score", "raison"]


def upsert_vigilance_review(conn: sqlite3.Connection, review: dict) -> str:
    payload = {
        "review_status": None,
        "queries_tried": 0,
        "new_urls_found": 0,
        "closures_created": 0,
        **review,
        "reviewed_at": review.get("reviewed_at") or datetime.now(timezone.utc).isoformat(),
    }
    conn.execute(
        """INSERT INTO vigilance_reviews
           (id, reviewed_at, review_status, queries_tried, new_urls_found, closures_created)
           VALUES (:id,:reviewed_at,:review_status,:queries_tried,:new_urls_found,:closures_created)
           ON CONFLICT(id) DO UPDATE SET
             reviewed_at=excluded.reviewed_at,
             review_status=excluded.review_status,
             queries_tried=excluded.queries_tried,
             new_urls_found=excluded.new_urls_found,
             closures_created=excluded.closures_created""",
        payload,
    )
    conn.commit()
    return review["id"]


def vigilance_review_recent(conn: sqlite3.Connection, vid: str, cooldown_days: int) -> bool:
    """True si la vigilance a déjà été revue il y a moins de `cooldown_days` jours."""
    row = conn.execute(
        "SELECT reviewed_at FROM vigilance_reviews WHERE id=?", (vid,)
    ).fetchone()
    if not row or not row[0]:
        return False
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=cooldown_days)).isoformat()
    return row[0] >= cutoff


# Marqueurs de sources presse locale / agrégateurs web à prioriser pour la revue
# arborescente : ce sont elles qui portent une commune/agence exploitable.
_PQR_MARKERS = (
    "google news", "actu", "ouest-france", "ouest france", "ici",
    "est republicain", "est républicain", "nouvelle republique",
    "nouvelle république", "dna", "info-chalon", "info chalon", "delta fm",
    "europesays", "europe says", "bien public", "progres", "progrès",
    "dauphine", "dauphiné", "sud ouest", "voix du nord", "france bleu",
    "republicain lorrain", "paris-normandie", "depeche", "dépêche",
    "telegramme", "télégramme", "brave", "bing", "sitemap", "presse",
)

# Titre contenant un lieu : nom propre composé (Bar-le-Duc, Saint-Cyr...) ou un
# nom capitalisé après une préposition de lieu (« à Reuilly », « de Colmar »).
_LIEU_DANS_TITRE = re.compile(
    r"[A-ZÀ-Ý][a-zà-ÿ'’]+-[A-Za-zà-ÿ'’]+"
    r"|(?:\bà|\bde|\bdes|\baux?)\s+[A-ZÀ-Ý][a-zà-ÿ'’]{2,}",
)

_FERMETURE_AGENCE = re.compile(
    r"\b(fermeture|fermetures|ferme|fermer|fermera|fermeront|fermé|fermée|"
    r"suppression|supprime|regroupement)\b.{0,90}"
    r"\b(agence|agences|banque|bancaire|guichet|succursale)\b"
    r"|"
    r"\b(agence|agences|banque|bancaire|guichet|succursale)\b.{0,90}"
    r"\b(fermeture|fermetures|ferme|fermer|fermera|fermeront|fermé|fermée|"
    r"suppression|supprime|regroupement)\b",
    re.IGNORECASE | re.DOTALL,
)


def _source_est_pqr(source: str | None) -> bool:
    s = (source or "").lower()
    return any(m in s for m in _PQR_MARKERS)


def _source_est_legifrance(source: str | None) -> bool:
    s = (source or "").lower()
    return "legifrance" in s or "légifrance" in s


def _priorite_revue(vig: dict) -> int:
    """Score de priorité de revue : PQR + titre localisé + plan d'abord."""
    from backend.drilldown import est_plan

    priorite = (vig.get("score") or 0) * 10
    source = vig.get("source")
    if _source_est_pqr(source):
        priorite += 50
    if _source_est_legifrance(source):
        priorite -= 40
    titre = vig.get("titre") or ""
    texte = f"{titre} {vig.get('extrait','')}"
    if _FERMETURE_AGENCE.search(texte):
        priorite += 45
    if est_plan(f"{titre} {vig.get('extrait','')}"):
        priorite += 30
    if _LIEU_DANS_TITRE.search(titre):
        priorite += 20
    return priorite


def select_vigilances_a_reviser(
    conn: sqlite3.Connection, min_score: int, max_per_run: int, cooldown_days: int,
    inclure_legifrance: bool = False,
) -> list[dict]:
    """Vigilances à revoir, classées par exploitabilité plutôt que par seul score.

    Priorité : presse locale/agrégateurs web (PQR, Google News, ICI, Actu…) +
    titre contenant une commune/localisation + plans multi-agences. Légifrance
    est exclu par défaut de la revue arborescente (peu exploitable, contexte
    pauvre), sauf `inclure_legifrance=True`.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=cooldown_days)).isoformat()
    cols = ",".join(f"v.{c}" for c in _VIGILANCE_SELECT_COLS)
    rows = conn.execute(
        f"""SELECT {cols}
            FROM vigilances v
            LEFT JOIN vigilance_reviews r ON v.id = r.id
            WHERE v.score >= ?
              AND (r.id IS NULL OR r.reviewed_at < ?)
            ORDER BY v.score DESC, v.date DESC""",
        (min_score, cutoff),
    ).fetchall()
    candidats = [dict(zip(_VIGILANCE_SELECT_COLS, row)) for row in rows]
    if not inclure_legifrance:
        candidats = [v for v in candidats if not _source_est_legifrance(v.get("source"))]
    # Tri stable par priorité décroissante (conserve l'ordre score/date en cas d'égalité).
    candidats.sort(key=_priorite_revue, reverse=True)
    return candidats[:max_per_run]
