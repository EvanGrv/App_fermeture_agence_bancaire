"""Mapping du schéma riche d'extraction vers le stockage actuel.

Le Cycle 2c-i produit un ExtractionResult large, mais les tables explicites
closures_unlocated / department_signals arrivent plus tard. Ici on traduit donc
vers les tables existantes : closures précises + au plus une vigilance agrégée
par article, pour respecter UNIQUE(url).
"""
from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from backend.dedup import closure_id
from backend.extractor import banque_connue, normalise_banque

_TYPE_MAP = {
    "closure": "fermeture",
    "transfer": "fermeture",
    "threatened_closure": "fermeture",
    "regroupement": "fusion",
    "merge": "fusion",
}
_STATUT_MAP = {
    "confirmed": "confirmé",
    "announced": "projet",
    "contested": "rumeur",
    "threatened": "rumeur",
    "unclear": "rumeur",
}


def _as_dict(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value if isinstance(value, dict) else {}


def _fiabilite(confidence: Any) -> int:
    try:
        return max(0, min(5, round(float(confidence) * 5)))
    except (TypeError, ValueError):
        return 0


def _statut_temporel(closure_date: Any, status: str | None, aujourdhui: str) -> str:
    if closure_date:
        try:
            fermeture = date.fromisoformat(str(closure_date)[:10])
            today = date.fromisoformat(str(aujourdhui)[:10])
            return "a_venir" if fermeture >= today else "deja_fermee"
        except ValueError:
            pass
    return "a_venir" if status in {"announced", "threatened"} else "inconnu"


def _map_closure(closure: Any, article: dict, aujourdhui: str) -> dict | None:
    c = _as_dict(closure)
    if not c.get("is_physical_agency", True):
        return None
    commune = (c.get("commune") or "").strip()
    if not commune:
        return None
    banque = normalise_banque(c.get("bank") or "")
    if not banque_connue(banque):
        return None

    type_ = _TYPE_MAP.get(c.get("closure_type"), "fermeture")
    date_precision = c.get("date_precision") or "unknown"
    return {
        "id": closure_id(banque, commune, type_, c.get("address") or ""),
        "banque": banque,
        "commune": commune,
        "code_insee": None,
        "departement": c.get("departement") or article.get("departement"),
        "type": type_,
        "date_annonce": article.get("date") or None,
        "date_fermeture": c.get("closure_date"),
        "statut": _STATUT_MAP.get(c.get("status"), "rumeur"),
        "statut_temporel": _statut_temporel(
            c.get("closure_date"), c.get("status"), aujourdhui
        ),
        "date_fermeture_approx": 0 if date_precision == "exact" else 1,
        "fiabilite": _fiabilite(c.get("confidence")),
        "lat": None,
        "lon": None,
        "citation": c.get("evidence") or "",
        "adresse": c.get("address") or None,
        "agence_localisation": c.get("agency_label") or None,
    }


def _aggregate_vigilance(
    dept_signals: list[Any], vague_signals: list[Any], article: dict
) -> dict:
    parts: list[str] = []
    evidences: list[str] = []
    scores: list[int] = []
    banque = None
    departement = None

    for raw in dept_signals:
        signal = _as_dict(raw)
        bank = normalise_banque(signal.get("bank") or "") if signal.get("bank") else None
        banque = banque or bank
        departement = departement or signal.get("departement")
        communes = ", ".join(signal.get("communes_mentioned") or [])
        parts.append(
            f"dept({bank},{signal.get('departement')},count={signal.get('count')},communes={communes})"
        )
        if signal.get("evidence"):
            evidences.append(signal["evidence"])
        scores.append(_fiabilite(signal.get("confidence")))

    for raw in vague_signals:
        signal = _as_dict(raw)
        bank = normalise_banque(signal.get("bank") or "") if signal.get("bank") else None
        banque = banque or bank
        parts.append(f"vague({bank},{signal.get('scope')},count={signal.get('count')})")
        if signal.get("evidence"):
            evidences.append(signal["evidence"])
        scores.append(_fiabilite(signal.get("confidence")))

    url = article.get("url") or None
    key = url or f"{article.get('titre') or ''}|{article.get('date') or ''}"
    return {
        "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
        "banque": banque,
        "departement": departement,
        "titre": article.get("titre"),
        "extrait": " | ".join(evidences)[:500],
        "url": url,
        "source": article.get("source"),
        "date": article.get("date"),
        "score": max(scores) if scores else 0,
        "raison": "signaux: " + "; ".join(parts),
    }


def map_result(result: dict, article: dict, aujourdhui: str) -> tuple[list[dict], dict | None]:
    """Traduit un ExtractionResult dict/Pydantic vers closures + vigilance agrégée."""
    data = _as_dict(result)
    closures = [
        mapped
        for mapped in (
            _map_closure(raw, article, aujourdhui)
            for raw in (data.get("closures") or [])
        )
        if mapped is not None
    ]
    dept = data.get("department_signals") or []
    vague = data.get("vague_signals") or []
    vigilance = _aggregate_vigilance(dept, vague, article) if (dept or vague) else None
    return closures, vigilance
