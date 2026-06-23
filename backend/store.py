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
"""


def init_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
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
             date_fermeture, statut, fiabilite, lat, lon, citation, created_at)
            VALUES (:id,:banque,:commune,:code_insee,:departement,:type,:date_annonce,
                    :date_fermeture,:statut,:fiabilite,:lat,:lon,:citation,:created_at)""",
            {**closure, "created_at": datetime.now(timezone.utc).isoformat()},
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
