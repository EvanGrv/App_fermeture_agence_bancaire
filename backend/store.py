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
    for col in ("adresse", "agence_localisation", "commune_originale"):
        if col not in existing:
            conn.execute(f"ALTER TABLE closures ADD COLUMN {col} TEXT")


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
             statut_temporel, date_fermeture_approx,
             adresse, agence_localisation, commune_originale, created_at)
            VALUES (:id,:banque,:commune,:code_insee,:departement,:type,:date_annonce,
                    :date_fermeture,:statut,:fiabilite,:lat,:lon,:citation,
                    :statut_temporel,:date_fermeture_approx,
                    :adresse,:agence_localisation,:commune_originale,:created_at)""",
            {
                "statut_temporel": "inconnu",
                "date_fermeture_approx": 0,
                "adresse": None,
                "agence_localisation": None,
                "commune_originale": None,
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
                lon=COALESCE(lon, ?),
                adresse=COALESCE(adresse, ?),
                agence_localisation=COALESCE(agence_localisation, ?),
                commune_originale=COALESCE(commune_originale, ?)
               WHERE id=?""",
            (fiab_max, closure.get("code_insee"), closure.get("date_fermeture"),
             closure.get("lat"), closure.get("lon"),
             closure.get("adresse"), closure.get("agence_localisation"),
             closure.get("commune_originale"), closure["id"]),
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
