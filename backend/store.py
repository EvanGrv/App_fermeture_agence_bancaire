# backend/store.py
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


def init_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    _ensure_closures_columns(conn)
    conn.commit()
    return conn


def upsert_closure(conn: sqlite3.Connection, closure: dict) -> str:
    existing = conn.execute(
        "SELECT fiabilite, code_insee, date_fermeture, lat, lon FROM closures WHERE id=?",
        (closure["id"],),
    ).fetchone()
    if existing is None:
        conn.execute(
            """INSERT INTO closures
            (id, banque, commune, code_insee, departement, type, date_annonce,
             date_fermeture, statut, fiabilite, lat, lon, citation,
             statut_temporel, date_fermeture_approx, created_at)
            VALUES (:id,:banque,:commune,:code_insee,:departement,:type,:date_annonce,
                    :date_fermeture,:statut,:fiabilite,:lat,:lon,:citation,
                    :statut_temporel,:date_fermeture_approx,:created_at)""",
            {
                "statut_temporel": "inconnu",
                "date_fermeture_approx": 0,
                **closure,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    else:
        fiab_max = max(existing[0] or 0, closure.get("fiabilite") or 0)
        conn.execute(
            """UPDATE closures SET
                fiabilite=?,
                code_insee=COALESCE(code_insee, ?),
                date_fermeture=COALESCE(date_fermeture, ?),
                lat=COALESCE(lat, ?),
                lon=COALESCE(lon, ?)
               WHERE id=?""",
            (fiab_max, closure.get("code_insee"), closure.get("date_fermeture"),
             closure.get("lat"), closure.get("lon"), closure["id"]),
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
