"""Gardes-fous déterministes entre une extraction et son article source."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Callable

import config
from backend import store, validation


@dataclass(frozen=True)
class GuardDecision:
    accepted: bool
    reason: str | None = None


_NEGATION_RE = re.compile(
    r"\b(?:ne|n)\s+(?:fermera|fermeront|ferme|ferment)\s+pas\b|"
    r"\bfermeture\s+(?:annulee|ecartee|abandonnee)\b|"
    r"\brenonce\s+a\s+(?:la\s+)?fermeture\b|"
    r"\bmaintien\s+(?:du|des)\s+(?:bureau|bureaux|agence|agences)\b"
)
_TEMPORARY_RE = re.compile(
    r"\bfermeture\s+(?:temporaire|exceptionnelle)\b|\btemporairement\s+ferm|"
    r"\bferm\w*\s+temporairement\b|"
    r"\b(?:provisoire|provisoirement)\b|"
    r"\b(?:travaux|renovation|modernisation|reparation|demenagement|demenager)\b|"
    r"\bjusqu[\s']+(?:a|au)\b|\bduree\s+indeterminee\b|"
    r"\btout[\s']+l[\s']+ete\b|"
    r"\b(?:pour|pendant|durant|depuis|plus\s+(?:de|d[\s']))\s+"
    r"(?:plus\s+(?:de|d[\s']))?"
    r"(?:\d+|un|une|deux|trois|quatre|cinq|six|plusieurs)\s+"
    r"(?:jours?|semaines?|mois)\b|"
    r"\bferm\w*\s+depuis\s+"
    r"(?:janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\b|"
    r"\b(?:raisons?\s+de\s+securite|infiltration|inondation|cambriolage|"
    r"agression|incivilites?|radon|sinistre)\b|"
    r"\bferme\s+(?:ce|le|chaque)\s+(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b"
)
_CLOSURE_MONTH_RE = re.compile(
    r"\b(?:fermeture|ferme|fermera|fermeront|fermee|fermees)\b"
    r"[^.!?]{0,55}?\b(?:en|au|le|des\s+le)\s+"
    r"(?:[0-3]?\d(?:er)?\s+)?"
    r"(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\b"
)
_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}


def _ascii(value: str | None) -> str:
    value = (value or "").replace("’", "'")
    value = "".join(
        char for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", value.lower()).strip()


def _location_pattern(value: str | None) -> re.Pattern | None:
    value = _ascii(value)
    pieces = [p for p in re.split(r"[-\s'.,/]+", value) if p]
    if not pieces:
        return None
    location = r"[-\s']+".join(re.escape(piece) for piece in pieces)
    # Le tiret est autorisé après la commune (Poitiers-Sud), jamais avant
    # (Bourgneuf ne doit pas correspondre à Vierzon-Bourgneuf).
    return re.compile(rf"(?<![\w-]){location}(?!\w)")


def _mentioned(value: str | None, source_text: str) -> bool:
    pattern = _location_pattern(value)
    return bool(pattern and pattern.search(source_text))


def _source_text(article: dict) -> str:
    return _ascii(f"{article.get('titre') or ''} {article.get('texte') or ''}")


def _source_departments(article: dict, source_text: str) -> set[str]:
    departments: set[str] = set()
    metadata = str(article.get("departement") or "")
    if validation.departement_valide(metadata):
        departments.add(metadata)

    matches: list[tuple[int, int, str]] = []
    for code, name in config.DEPARTEMENTS.items():
        pieces = [p for p in re.split(r"[-\s']+", _ascii(name)) if p]
        key = r"[-\s']+".join(re.escape(piece) for piece in pieces)
        for match in re.finditer(rf"(?<!\w){key}(?!\w)", source_text):
            matches.append((match.start(), match.end(), code))
    # Les noms les plus longs priment : "Loire" n'est pas ajouté à côté de
    # "Loire-Atlantique" sur la même occurrence.
    occupied: list[tuple[int, int]] = []
    for start, end, code in sorted(matches, key=lambda m: (m[0], -(m[1] - m[0]))):
        if any(start < other_end and end > other_start for other_start, other_end in occupied):
            continue
        occupied.append((start, end))
        departments.add(code)
    for match in re.finditer(r"\(([0-9]{2,3}|2[ab])\)", source_text):
        code = match.group(1).upper()
        if validation.departement_valide(code):
            departments.add(code)
    return departments


def source_departments(article: dict) -> set[str]:
    """Départements explicitement étayés par les métadonnées ou le texte source."""
    return _source_departments(article, _source_text(article))


def enrich_department_from_source(closure: dict, article: dict) -> set[str]:
    """Complète un département absent uniquement si la source n'en indique qu'un."""
    departments = source_departments(article)
    if (
        not validation.departement_valide(closure.get("departement"))
        and len(departments) == 1
    ):
        closure["departement"] = next(iter(departments))
    return departments


def _leading_location(title: str | None) -> str | None:
    title = (title or "").strip()
    patterns = (
        r"^[ÀA]\s+([A-ZÀ-Ý][A-Za-zÀ-ÿ'’-]+(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’-]+){0,3})\s*[, :]",
        r"^([A-ZÀ-Ý][A-Za-zÀ-ÿ'’-]+(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’-]+){0,3})\s*:",
    )
    for pattern in patterns:
        match = re.search(pattern, title)
        if match and validation.commune_publiable(match.group(1)):
            return match.group(1)
    return None


def evaluate(
    closure: dict,
    article: dict,
    geo: dict | None,
    *,
    geocode_fn: Callable[..., dict | None] | None = None,
    require_location: bool = True,
) -> GuardDecision:
    """Compare les champs publiés aux éléments vérifiables dans la source."""
    source_text = _source_text(article)
    banque = closure.get("banque") or ""

    if (geo or {}).get("ambiguous"):
        candidates = ", ".join(
            f"{item.get('commune')} ({item.get('departement')})"
            for item in (geo or {}).get("candidates", [])
        )
        suffix = f": {candidates}" if candidates else ""
        return GuardDecision(
            False,
            f"garde entrée/sortie: commune homonyme sans département vérifiable{suffix}",
        )

    if _NEGATION_RE.search(source_text):
        return GuardDecision(False, "garde entrée/sortie: la source nie ou annule la fermeture")
    if banque == "La Banque Postale" and _TEMPORARY_RE.search(source_text):
        return GuardDecision(False, "garde entrée/sortie: fermeture postale temporaire ou circonstancielle")

    geo_department = str((geo or {}).get("departement") or closure.get("departement") or "")
    source_departments = _source_departments(article, source_text)
    if source_departments and geo_department and geo_department not in source_departments:
        named = ", ".join(sorted(source_departments))
        return GuardDecision(
            False,
            f"garde entrée/sortie: département source {named} incompatible avec la sortie {geo_department}",
        )

    # Même si l'IA fournit un département, une commune homonyme ne peut être
    # publiée que si ce département est étayé par la source. La recherche BAN
    # non contrainte sert uniquement à détecter l'homonymie.
    if (
        require_location
        and geocode_fn
        and closure.get("commune")
        and not source_departments
    ):
        try:
            unscoped_geo = geocode_fn(closure["commune"], None)
        except Exception:
            unscoped_geo = None
        if (unscoped_geo or {}).get("ambiguous"):
            return GuardDecision(
                False,
                "garde entrée/sortie: commune homonyme sans département vérifiable dans la source",
            )

    if require_location:
        expected = [
            article.get("commune_attendue"),
            *(article.get("seed_communes") or []),
            *(target.get("commune") for target in (article.get("seed_targets") or [])),
        ]
        source_supports_location = any(
            candidate and _ascii(candidate) == _ascii(closure.get("commune"))
            for candidate in expected
        )
        source_supports_location = source_supports_location or _mentioned(
            closure.get("commune"), source_text
        )
        source_supports_location = source_supports_location or _mentioned(
            closure.get("agence_localisation"), source_text
        )
        if not source_supports_location:
            return GuardDecision(
                False,
                "garde entrée/sortie: commune/localisation de sortie absente de la source",
            )

        leading = _leading_location(article.get("titre"))
        if leading and not _mentioned(closure.get("commune"), _ascii(leading)) and geocode_fn:
            try:
                leading_geo = geocode_fn(leading, article.get("departement"))
            except Exception:
                leading_geo = None
            if (
                leading_geo
                and geo
                and leading_geo.get("code_insee")
                and geo.get("code_insee")
                and leading_geo["code_insee"] != geo["code_insee"]
            ):
                return GuardDecision(
                    False,
                    f"garde entrée/sortie: lieu d’article {leading} incompatible avec la commune de sortie",
                )

    if closure.get("date_fermeture_approx") and closure.get("date_fermeture"):
        month_match = _CLOSURE_MONTH_RE.search(source_text)
        if month_match:
            try:
                output_month = date.fromisoformat(closure["date_fermeture"]).month
            except (TypeError, ValueError):
                output_month = None
            source_month = _MONTHS[month_match.group(1)]
            if output_month and output_month != source_month:
                return GuardDecision(
                    False,
                    "garde entrée/sortie: mois de fermeture incompatible avec la source",
                )

    return GuardDecision(True)


def quarantine_existing_lbp(conn, geocode_fn=None) -> dict:
    """Retire les anciens marqueurs LBP contredits avec certitude par leur titre."""
    rows = conn.execute(
        """SELECT c.id, c.commune, c.departement, c.type, c.date_fermeture,
                  c.statut, c.statut_temporel, c.fiabilite, c.citation,
                  c.date_fermeture_approx, c.agence_localisation,
                  c.evidence_level, c.lat, c.lon,
                  s.url, s.titre, s.source, s.date
           FROM closures c JOIN sources s ON s.closure_id=c.id
           WHERE c.banque='La Banque Postale'
             AND COALESCE(c.evidence_level, '') NOT LIKE 'officiel%'
             AND COALESCE(s.source, '') != 'La Poste Open Data'
           ORDER BY c.id"""
    ).fetchall()
    by_closure: dict[str, list[tuple]] = {}
    for row in rows:
        by_closure.setdefault(row[0], []).append(row)

    quarantined = 0
    reasons: dict[str, int] = {}
    for closure_id, sources in by_closure.items():
        first = sources[0]
        closure = {
            "id": closure_id, "banque": "La Banque Postale", "commune": first[1],
            "departement": first[2], "type": first[3], "date_fermeture": first[4],
            "statut": first[5], "statut_temporel": first[6], "fiabilite": first[7],
            "citation": first[8], "date_fermeture_approx": first[9],
            "agence_localisation": first[10],
        }
        geo = {"departement": first[2], "lat": first[12], "lon": first[13]}
        decisions = []
        for row in sources:
            article = {
                "titre": row[15], "texte": "", "url": row[14],
                "source": row[16], "date": row[17], "departement": None,
            }
            decision = (
                evaluate(
                    closure,
                    article,
                    geo,
                    geocode_fn=geocode_fn,
                    require_location=True,
                )
                if article["titre"]
                else GuardDecision(True)
            )
            decisions.append((decision, article))
        # Une seconde source non contradictoire suffit à conserver le marqueur.
        if any(decision.accepted for decision, _article in decisions):
            continue
        reason = decisions[0][0].reason or "garde entrée/sortie: source incohérente"
        article = decisions[0][1]
        unlocated_id = hashlib.sha256(f"quarantine|{closure_id}".encode()).hexdigest()[:16]
        store.upsert_closure_unlocated(conn, {
            **closure,
            "id": unlocated_id,
            "url": article.get("url"), "titre": article.get("titre"),
            "source": article.get("source"), "date": article.get("date"),
            "raison": reason,
        })
        conn.execute("DELETE FROM controles_sirene WHERE closure_id=?", (closure_id,))
        conn.execute("DELETE FROM sources WHERE closure_id=?", (closure_id,))
        conn.execute("DELETE FROM closures WHERE id=?", (closure_id,))
        conn.commit()
        quarantined += 1
        reasons[reason] = reasons.get(reason, 0) + 1
    return {"quarantined": quarantined, "reasons": reasons}
