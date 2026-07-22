"""Passe descendante commune par commune (drill-down depuis les plans départementaux).

Heuristic + BAN-validation approach, no extra AI cost.

Usage dans run.py :
    from backend import drilldown
    plan_articles = google_news.collect(queries=drilldown.PLAN_SCAN_QUERIES)
    drill_queries = drilldown.requetes_depuis_articles(plan_articles, geo_commune)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

import config
from backend.dedup import closure_id
from backend.extractor import normalise_banque

# ---------------------------------------------------------------------------
# Requêtes de scan dédiées aux plans multi-agences
# ---------------------------------------------------------------------------

PLAN_SCAN_QUERIES = [
    "plan de fermeture agences bancaires",
    "fermeture de plusieurs agences bancaires",
    "réorganisation du réseau bancaire agences",
    "banque ferme plusieurs agences département",
]

# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _normalise(texte: str) -> str:
    """Supprime les accents et met en minuscules (comme prefilter._normalise)."""
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn"
    )
    return sans_accents.lower()


# Pattern : (nombre ≥ 2 ou mot-nombre) suivi de jusqu'à ~40 chars avant "agences"
# On utilise .{0,40} (lazy) pour gérer les apostrophes (d'agences, vingtaine d'agences…).
_PLAN_QUANTITE = re.compile(
    r"(?:(?:[2-9]|\d{2,})|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|douze|quinze|vingt"
    r"|plusieurs|une\s+vingtaine|une\s+dizaine)"
    r".{0,40}agences",
    re.IGNORECASE,
)

# Phrases-clés signalant un plan même sans quantité explicite
_PLAN_PHRASES = re.compile(
    r"plan\s+de\s+fermeture"
    r"|reorganisation\s+du\s+reseau"
    r"|reorganisation\s+territoriale",
    re.IGNORECASE,
)


def est_plan(texte: str) -> bool:
    """True si le texte signale un plan de fermeture multi-agences."""
    t_norm = _normalise(texte)
    if _PLAN_PHRASES.search(t_norm):
        return True
    if _PLAN_QUANTITE.search(t_norm):
        return True
    return False


# ---------------------------------------------------------------------------
# Extraction des candidats communes
# ---------------------------------------------------------------------------

# Cues de localisation qui précèdent une liste de communes
_CUES = re.compile(
    r"(?:agences?\s+de|communes?\s+de|sites?\s+de|"
    r"\bagences?\b.*?\b(?:à|a)\b|\b(?:à|a)\b)",
    re.IGNORECASE,
)

# Motif de séparation dans une liste
_SEP = re.compile(r",\s*|\s+et\s+", re.IGNORECASE)

# Fin de span : ponctuation terminale ou fin de phrase
_END = re.compile(r"[.!?;:\n]")

# Extrait le nom de commune proprement dit depuis le début d'un segment.
# Un nom de commune est une séquence de mots commençant par une majuscule
# (avec tirets et apostrophes), chaque mot pouvant être suivi par un autre
# mot également en majuscule. Les mots en minuscule arrêtent l'extraction.
# Exemples : "Bessines", "Saint-Junien", "La Rochelle", "Le Mont-Saint-Michel"
_PROPER_NAME = re.compile(
    r"^([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÆŒÇ][a-zA-ZÀ-ÖØ-öø-ÿ'\-]+"
    r"(?:(?:\s+(?:de|du|des|d'|d’|le|la|les|lès|sur|sous|au|aux)\s+|\s+)"
    r"[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÆŒÇ][a-zA-ZÀ-ÖØ-öø-ÿ'\-]+)*)"
)


def communes_candidates(texte: str) -> list[str]:
    """Extrait les noms de communes candidats depuis des énumérations dans le texte."""
    results: list[str] = []
    seen: set[str] = set()

    for m in _CUES.finditer(texte):
        start = m.end()
        # Trouver la fin du span : prochain marqueur de fin de phrase ou 200 chars
        end_m = _END.search(texte, start)
        end = end_m.start() if end_m else min(start + 200, len(texte))
        span = texte[start:end].strip()
        if not span:
            continue

        parts = _SEP.split(span)
        for part in parts:
            segment = part.strip()
            if not segment:
                continue
            # Rejeter les segments avec des chiffres
            if any(c.isdigit() for c in segment):
                continue
            # Extraire uniquement la partie "nom propre" depuis le début du segment
            pm = _PROPER_NAME.match(segment)
            if not pm:
                continue
            token = pm.group(1)
            if token not in seen:
                seen.add(token)
                results.append(token)
            if len(results) >= 20:
                return results

    return results


# ---------------------------------------------------------------------------
# Validation BAN
# ---------------------------------------------------------------------------

def valider_communes(
    candidates: list[str],
    geocode_fn: Callable[[str], dict | None],
) -> list[str]:
    """Valide les candidats via BAN. Garde ceux avec un code_insee réel."""
    seen: set[str] = set()
    valides: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            result = geocode_fn(candidate)
        except Exception:
            continue
        if result and result.get("code_insee"):
            valides.append(candidate)
        if len(valides) >= 8:
            break
    return valides


# ---------------------------------------------------------------------------
# Détection de la banque
# ---------------------------------------------------------------------------

# Construire la liste de toutes les variantes (enseignes + marques régionales)
# ordonnées du plus long au plus court pour matcher les marques spécifiques en premier
def _build_variantes() -> list[str]:
    variantes: list[str] = list(config.ENSEIGNES)
    for vs in getattr(config, "MARQUES_REGIONALES", {}).values():
        variantes.extend(vs)
    # Trier du plus long au plus court pour matcher les formes les plus spécifiques en premier
    return sorted(set(variantes), key=len, reverse=True)


_VARIANTES = _build_variantes()
_VARIANTES_NORM = [(_normalise(v), v) for v in _VARIANTES]


def _detecter_banque(texte: str) -> str | None:
    """Trouve la première enseigne ou marque régionale dans le texte normalisé."""
    t_norm = _normalise(texte)
    for norm_v, orig_v in _VARIANTES_NORM:
        if norm_v in t_norm:
            return normalise_banque(orig_v)
    return None


# ---------------------------------------------------------------------------
# Construction des requêtes
# ---------------------------------------------------------------------------

def requetes_communes(banque: str, communes: list[str]) -> list[str]:
    """Construit une requête ciblée pour chaque commune."""
    return [f"{banque} fermeture agence {commune}" for commune in communes]


# ---------------------------------------------------------------------------
# Éclatement d'un plan en fermetures individuelles (Phase 3)
# ---------------------------------------------------------------------------

_MOIS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12,
}

_DATE_PLAN = re.compile(
    r"(\d{1,2})\s*(?:er)?\s+(" + "|".join(_MOIS) + r")\s+(\d{4})",
    re.IGNORECASE,
)


def date_commune_du_plan(texte: str) -> str | None:
    """Extrait la date commune d'un plan ("1er septembre 2026" -> "2026-09-01")."""
    m = _DATE_PLAN.search(_normalise(texte or ""))
    if not m:
        return None
    jour = int(m.group(1))
    mois = _MOIS[m.group(2)]
    annee = int(m.group(3))
    try:
        from datetime import date
        return date(annee, mois, jour).isoformat()
    except ValueError:
        return None


def valider_communes_geo(
    candidates: list[str],
    geocode_fn: Callable[[str], dict | None],
    max_communes: int,
) -> list[tuple[str, dict]]:
    """Valide les candidats via BAN et retourne (commune, geo) pour ceux retenus."""
    seen: set[str] = set()
    valides: list[tuple[str, dict]] = []
    for candidate in candidates:
        cle = _normalise(candidate)
        if cle in seen:
            continue
        seen.add(cle)
        try:
            geo = geocode_fn(candidate)
        except Exception:
            continue
        if geo and geo.get("code_insee"):
            valides.append((candidate, geo))
        if len(valides) >= max_communes:
            break
    return valides


def fermetures_depuis_plan(
    article: dict,
    geocode_fn: Callable[[str], dict | None],
    max_communes: int | None = None,
    fetch_fn: Callable[[str], str] | None = None,
) -> list[dict]:
    """Transforme un article "plan multi-agences" en N fermetures (une par commune).

    Best-effort : retourne [] si l'article n'est pas un plan, si la banque n'est
    pas identifiable, ou si aucune commune ne se valide via la BAN.
    """
    if max_communes is None:
        max_communes = config.PLAN_EXPLOSION_MAX_COMMUNES

    titre = article.get("titre", "") or ""
    texte = article.get("texte", "") or ""
    url = article.get("url", "") or ""
    # Forcer le fulltext si le snippet est trop court pour repérer la liste.
    if fetch_fn and url and len(texte) < 400:
        try:
            complet = fetch_fn(url)
            if complet:
                texte = (texte + "\n\n" + complet)[:6000]
                article["texte"] = texte
        except Exception:
            pass
    contenu = f"{titre} {texte}"

    if not est_plan(contenu):
        return []
    banque = _detecter_banque(contenu)
    if banque is None:
        return []

    date_f = date_commune_du_plan(contenu)
    candidates = communes_candidates(contenu)
    valides = valider_communes_geo(candidates, geocode_fn, max_communes)
    if not valides:
        return []

    citation = titre.strip() or contenu[:200]
    closures: list[dict] = []
    for commune, geo in valides:
        closures.append({
            "id": closure_id(banque, commune, "fermeture"),
            "banque": banque,
            "commune": commune,
            "code_insee": geo.get("code_insee"),
            "departement": geo.get("departement"),
            "type": "fermeture",
            "date_annonce": article.get("date") or None,
            "date_fermeture": date_f,
            "statut": "projet",
            "statut_temporel": "a_venir",
            "date_fermeture_approx": 0,
            "fiabilite": 3,
            "lat": geo.get("lat"),
            "lon": geo.get("lon"),
            "citation": citation,
        })
    return closures


# ---------------------------------------------------------------------------
# Orchestration : articles → requêtes drill-down
# ---------------------------------------------------------------------------

def requetes_depuis_articles(
    articles: list[dict],
    geocode_fn: Callable[[str], dict | None],
    max_total: int = 50,
) -> list[str]:
    """Analyse les articles de plan, valide les communes, construit les requêtes.

    Args:
        articles: liste d'articles (dicts avec 'titre' et 'texte').
        geocode_fn: callable(commune: str) → dict | None (BAN validator).
        max_total: nombre max de requêtes retournées (tronqué après dedup).

    Returns:
        Liste de requêtes déduplicées, tronquée à max_total.
    """
    seen_queries: set[str] = set()
    all_queries: list[str] = []

    for article in articles:
        titre = article.get("titre", "") or ""
        texte = article.get("texte", "") or ""
        contenu = f"{titre} {texte}"

        if not est_plan(contenu):
            continue

        banque = _detecter_banque(contenu)
        if banque is None:
            continue

        candidates = communes_candidates(contenu)
        if not candidates:
            continue

        valides = valider_communes(candidates, geocode_fn)
        if not valides:
            continue

        for q in requetes_communes(banque, valides):
            if q not in seen_queries:
                seen_queries.add(q)
                all_queries.append(q)
            if len(all_queries) >= max_total:
                return all_queries

    return all_queries
