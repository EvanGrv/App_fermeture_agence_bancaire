"""Observation du réseau postal officiel et qualification des pertes LBP.

La liste nationale sert de référentiel versionné. On conserve l'état courant
et une ligne d'historique uniquement lors d'un changement. Le calendrier à
trois mois est interrogé de façon ciblée pour les fermetures LBP déjà détectées.
"""
from __future__ import annotations

import hashlib
import urllib.parse
from datetime import date, datetime, timezone

import requests

import config
from backend import store
from backend.dedup import closure_id, normalise_cle

POINTS_PAGE = "https://data.laposte.fr/datasets/laposte-poincont2"
CALENDAR_PAGE = "https://data.laposte.fr/datasets/tjwztt6h44ve52i7fln6rbxz"
_POINT_FIELDS = (
    "identifiant_a,libelle_du_site,caracteristique_du_site,adresse,"
    "code_postal,localite,code_insee,latitude,longitude"
)
_FULL_OFFICE_TYPES = {"bureau de poste", "bureau centre"}
_PARTNER_TYPES = {
    "agence postale communale", "agence postale intercommunale",
    "agence postale communale ou intercommunale", "relais poste",
    "point partenaire", "agence postale ou relais poste",
}


def _default_fetch(url: str) -> dict:
    response = requests.get(url, timeout=45, headers={"User-Agent": "veille-presse/1.0"})
    response.raise_for_status()
    return response.json()


def _dataset_url(dataset_id: str, suffix: str = "") -> str:
    return f"{config.LAPOSTE_DATA_API_BASE.rstrip('/')}/{dataset_id}{suffix}"


def fetch_revision(fetch=_default_fetch) -> str:
    payload = fetch(_dataset_url(config.LAPOSTE_POINTS_DATASET_ID))
    return str(payload.get("dataUpdatedAt") or payload.get("updatedAt") or "").strip()


def fetch_points(fetch=_default_fetch) -> list[dict]:
    params = urllib.parse.urlencode({"size": 10000, "select": _POINT_FIELDS})
    url = _dataset_url(config.LAPOSTE_POINTS_DATASET_ID, f"/lines?{params}")
    records: list[dict] = []
    while url:
        payload = fetch(url) or {}
        records.extend(payload.get("results") or [])
        url = payload.get("next")
    return [point for raw in records if (point := normalize_point(raw)) is not None]


def _department(code_insee: str | None, postal_code: str | None) -> str | None:
    insee = str(code_insee or "").strip()
    postal = str(postal_code or "").zfill(5)
    for candidate in (insee[:3], postal[:3], insee[:2], postal[:2]):
        if candidate in config.DEPARTEMENTS:
            return candidate
    return None


def normalize_point(raw: dict) -> dict | None:
    point_id = str(raw.get("identifiant_a") or raw.get("identifiant") or "").strip()
    if not point_id:
        return None
    postal_code = str(raw.get("code_postal") or "").strip()
    if postal_code.isdigit() and len(postal_code) < 5:
        postal_code = postal_code.zfill(5)
    code_insee = str(raw.get("code_insee") or "").strip()
    return {
        "point_id": point_id,
        "label": str(raw.get("libelle_du_site") or "").strip(),
        "characteristic": str(
            raw.get("caracteristique_du_site") or raw.get("caracteristique") or ""
        ).strip(),
        "address": str(raw.get("adresse") or "").strip(),
        "postal_code": postal_code,
        "locality": str(raw.get("localite") or "").strip(),
        "code_insee": code_insee,
        "departement": _department(code_insee, postal_code),
        "lat": raw.get("latitude"),
        "lon": raw.get("longitude"),
    }


def _is_full_office(point: dict) -> bool:
    return normalise_cle(point.get("characteristic") or "") in _FULL_OFFICE_TYPES


def _is_partner(point: dict) -> bool:
    return normalise_cle(point.get("characteristic") or "") in _PARTNER_TYPES


def _state(point: dict) -> tuple:
    return tuple(point.get(key) for key in (
        "label", "characteristic", "address", "postal_code", "locality",
        "code_insee", "departement", "lat", "lon", "active",
    ))


def _impact(replacement: dict | None) -> str:
    characteristic = normalise_cle((replacement or {}).get("characteristic") or "")
    if "agence postale" in characteristic:
        return "conversion_ap"
    if "relais" in characteristic or "partenaire" in characteristic:
        return "conversion_relais"
    return "fermeture_lbp_complete"


def _record_closure(conn, old: dict, revision: str, replacement: dict | None = None) -> str:
    observed_date = revision[:10] if len(revision) >= 10 else date.today().isoformat()
    commune = old.get("locality") or old.get("label") or "Commune non précisée"
    existing = conn.execute(
        """SELECT id FROM closures
           WHERE banque='La Banque Postale' AND code_insee=?
           ORDER BY created_at DESC LIMIT 2""",
        (old.get("code_insee"),),
    ).fetchall() if old.get("code_insee") else []
    cid = (
        existing[0][0] if len(existing) == 1 else
        closure_id("La Banque Postale", commune, "fermeture", old.get("address") or "")
    )
    replacement_type = (replacement or {}).get("characteristic")
    impact = _impact(replacement)
    citation = (
        f"Le référentiel officiel La Poste signale la conversion de "
        f"{old.get('label') or commune} en {replacement_type}."
        if replacement_type else
        f"Le point {old.get('label') or commune} a disparu de deux révisions "
        "successives du référentiel officiel La Poste."
    )
    store.upsert_closure(conn, {
        "id": cid, "banque": "La Banque Postale", "commune": commune,
        "code_insee": old.get("code_insee"), "departement": old.get("departement"),
        "type": "fermeture", "date_annonce": observed_date,
        "date_fermeture": observed_date, "statut": "confirmé", "fiabilite": 5,
        "lat": old.get("lat"), "lon": old.get("lon"), "citation": citation,
        "statut_temporel": "deja_fermee", "date_fermeture_approx": 1,
        "adresse": old.get("address"), "agence_localisation": old.get("label"),
        "service_impact": impact, "point_postal_avant": old.get("characteristic"),
        "point_postal_apres": replacement_type, "postal_point_id": old.get("point_id"),
        "evidence_level": "officiel",
    })
    store.add_source(conn, cid, {
        "url": POINTS_PAGE, "titre": "Liste officielle des points de contact La Poste",
        "source": "La Poste Open Data", "date": observed_date,
    })
    return cid


def _record_missing_vigilance(conn, point: dict, revision: str) -> None:
    raw_id = f"laposte-missing|{point.get('point_id')}|{revision}"
    vid = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]
    store.upsert_vigilance(conn, {
        "id": vid, "banque": "La Banque Postale",
        "departement": point.get("departement"),
        "titre": f"Disparition à confirmer du bureau de poste {point.get('label')}",
        "extrait": (
            "Le bureau de poste n'apparaît plus dans la dernière révision du "
            "référentiel officiel. Une seconde révision ou une source locale est requise."
        ),
        "url": f"{POINTS_PAGE}?point={urllib.parse.quote(point.get('point_id') or '')}",
        "source": "La Poste Open Data", "date": revision[:10], "score": 5,
        "raison": "disparition officielle à confirmer",
    })


def sync_network(conn, points: list[dict], revision: str,
                 observed_at: str | None = None) -> dict:
    """Compare une révision officielle au dernier état persistant."""
    if not revision or not points:
        return {"status": "empty", "points": 0, "closures": 0, "vigilances": 0}
    if store.postal_revision_seen(conn, revision):
        return {"status": "unchanged", "points": len(points), "closures": 0, "vigilances": 0}

    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    previous = store.postal_points(conn)
    current = {point["point_id"]: point for point in points}
    new_ids = set(current) - set(previous)
    closures = 0
    vigilances = 0

    for point_id, point in current.items():
        old = previous.get(point_id)
        stored = {
            **point, "active": 1, "missing_revisions": 0,
            "first_seen_revision": old.get("first_seen_revision") if old else revision,
            "last_seen_revision": revision, "updated_at": observed_at,
        }
        if old is None or _state(old) != _state(stored):
            store.add_postal_point_history(conn, stored, revision, observed_at)
        if old and _is_full_office(old) and not _is_full_office(point):
            _record_closure(conn, old, revision, point)
            closures += 1
        store.save_postal_point(conn, stored)

    for point_id, old in previous.items():
        if point_id in current or not _is_full_office(old):
            continue
        missing = int(old.get("missing_revisions") or 0) + 1
        candidates = [
            current[candidate_id] for candidate_id in new_ids
            if _is_partner(current[candidate_id])
            and (
                (
                    old.get("code_insee")
                    and current[candidate_id].get("code_insee") == old.get("code_insee")
                )
                or (
                    old.get("locality")
                    and normalise_cle(current[candidate_id].get("locality") or "")
                    == normalise_cle(old.get("locality") or "")
                )
            )
        ]
        replacement = candidates[0] if len(candidates) == 1 else None
        stored = {
            **old, "active": 0, "missing_revisions": missing,
            "last_seen_revision": old.get("last_seen_revision") or revision,
            "updated_at": observed_at,
        }
        store.save_postal_point(conn, stored)
        store.add_postal_point_history(conn, stored, revision, observed_at)
        if replacement or missing >= config.LAPOSTE_MISSING_CONFIRMATIONS:
            _record_closure(conn, old, revision, replacement)
            closures += 1
        else:
            _record_missing_vigilance(conn, old, revision)
            vigilances += 1

    # Le même référentiel alimente le dénominateur cartographique LBP. Seuls
    # les bureaux de plein exercice sont comptés comme agences bancaires.
    conn.execute("DELETE FROM referentiel WHERE source='La Poste Open Data'")
    for point in current.values():
        if not _is_full_office(point):
            continue
        conn.execute(
            """INSERT INTO referentiel
               (osm_id, banque, commune, code_postal, departement, lat, lon, source, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(osm_id) DO UPDATE SET banque=excluded.banque,
                 commune=excluded.commune, code_postal=excluded.code_postal,
                 departement=excluded.departement, lat=excluded.lat, lon=excluded.lon,
                 source=excluded.source""",
            (f"laposte/{point['point_id']}", "La Banque Postale", point.get("locality"),
             point.get("postal_code"), point.get("departement"), point.get("lat"),
             point.get("lon"), "La Poste Open Data", observed_at),
        )

    store.finish_postal_sync(conn, revision, observed_at, len(current))
    return {
        "status": "updated", "points": len(current),
        "closures": closures, "vigilances": vigilances,
    }


def sync_official_network(conn, fetch=_default_fetch) -> dict:
    if not config.LAPOSTE_OPEN_DATA_ENABLED:
        return {"status": "disabled", "points": 0, "closures": 0, "vigilances": 0}
    try:
        revision = fetch_revision(fetch)
        if store.postal_revision_seen(conn, revision):
            return {"status": "unchanged", "points": 0, "closures": 0, "vigilances": 0}
        return sync_network(conn, fetch_points(fetch), revision)
    except Exception as exc:
        print(f"[laposte_open_data] synchronisation impossible: {exc}")
        return {"status": "error", "points": 0, "closures": 0, "vigilances": 0}


def fetch_calendar(point_id: str, fetch=_default_fetch) -> list[dict]:
    params = urllib.parse.urlencode({"q": point_id, "size": 200})
    payload = fetch(_dataset_url(config.LAPOSTE_CALENDAR_DATASET_ID, f"/lines?{params}"))
    return [
        row for row in (payload.get("results") or [])
        if str(row.get("identifiant") or "") == point_id
    ]


def detect_banking_cutoff(rows: list[dict], minimum_closed_weekdays: int = 10) -> str | None:
    """Date du premier jour bancaire fermé après la dernière journée ouverte."""
    dated: list[tuple[date, bool]] = []
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("date_calendrier") or ""))
        except ValueError:
            continue
        values = [row.get("bp_plage_horaire_1"), row.get("bp_plage_horaire_2")]
        is_open = any(value and normalise_cle(str(value)) != "ferme" for value in values)
        dated.append((day, is_open))
    dated.sort()
    active_days = [day for day, is_open in dated if is_open]
    if not active_days:
        return None
    last_active = max(active_days)
    closed_after = [day for day, is_open in dated if day > last_active and day.weekday() < 5 and not is_open]
    if len(closed_after) < minimum_closed_weekdays:
        return None
    return min(closed_after).isoformat()


def enrich_lbp_closures(conn, fetch=_default_fetch) -> dict:
    """Rattache les fermetures presse à un bureau officiel et vérifie l'horizon."""
    rows = conn.execute(
        """SELECT id, code_insee, commune, statut, date_fermeture, postal_point_id
           FROM closures WHERE banque='La Banque Postale'
           ORDER BY created_at DESC"""
    ).fetchall()
    checked = matched = dated = 0
    for cid, code_insee, commune, statut, closure_date, point_id in rows:
        if not point_id:
            candidates = conn.execute(
                """SELECT point_id, label, characteristic FROM postal_points
                   WHERE active=1 AND code_insee=?""",
                (code_insee,),
            ).fetchall() if code_insee else []
            full = [candidate for candidate in candidates if _is_full_office({
                "characteristic": candidate[2]
            })]
            partners = [candidate for candidate in candidates if _is_partner({
                "characteristic": candidate[2]
            })]
            chosen = full[0] if len(full) == 1 else None
            if chosen is None and len(partners) == 1 and closure_date:
                chosen = partners[0]
            if chosen:
                point_id, label, characteristic = chosen
                replacement = None if _is_full_office({
                    "characteristic": characteristic
                }) else {"characteristic": characteristic}
                conn.execute(
                    """UPDATE closures SET postal_point_id=?, point_postal_avant=?,
                       point_postal_apres=COALESCE(point_postal_apres, ?),
                       service_impact=CASE WHEN ? IS NOT NULL THEN ?
                         ELSE COALESCE(service_impact, 'fermeture_lbp_complete') END,
                       evidence_level='presse+référentiel' WHERE id=?""",
                    (
                        point_id, "Bureau de Poste",
                        characteristic if replacement else None,
                        characteristic if replacement else None,
                        _impact(replacement), cid,
                    ),
                )
                conn.commit()
                matched += 1
        if not point_id or checked >= config.LAPOSTE_CALENDAR_MAX_CHECKS:
            continue
        if statut != "projet" and closure_date:
            continue
        point_state = conn.execute(
            "SELECT characteristic, active FROM postal_points WHERE point_id=?",
            (point_id,),
        ).fetchone()
        if not point_state or not point_state[1] or not _is_full_office({
            "characteristic": point_state[0]
        }):
            continue
        try:
            cutoff = detect_banking_cutoff(fetch_calendar(point_id, fetch))
        except Exception as exc:
            print(f"[laposte_open_data] calendrier {point_id} indisponible: {exc}")
            continue
        checked += 1
        if cutoff:
            conn.execute(
                """UPDATE closures SET date_fermeture=COALESCE(date_fermeture, ?),
                   evidence_level='officiel+presse', fiabilite=MAX(fiabilite, 5) WHERE id=?""",
                (cutoff, cid),
            )
            conn.commit()
            store.add_source(conn, cid, {
                "url": CALENDAR_PAGE, "titre": "Calendrier officiel des horaires Banque Postale",
                "source": "La Poste Open Data", "date": cutoff,
            })
            dated += 1
    return {"matched": matched, "calendar_checked": checked, "dated": dated}
