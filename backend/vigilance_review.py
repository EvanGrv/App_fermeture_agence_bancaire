"""Revue arborescente des vigilances (Phase 2).

Une vigilance n'est plus une fin de parcours : pour chaque signal d'un score
suffisant, on génère des recherches secondaires ciblées (banque + commune +
sources locales), on interroge les providers disponibles, on déduplique les
URLs, on relance l'extraction, et on publie une fermeture si elle devient
exploitable.

Le module est agnostique du provider : on injecte `search_fn(query) -> [articles]`.
Il peut donc fonctionner d'abord avec Google News / GDELT / RSS locaux existants,
puis avec Brave / Bing / sitemaps une fois branchés.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

import config
from backend import query_builder, validation
from backend.dedup import normalise_cle

# Séquences de mots à majuscule (noms propres) : "Bar-le-Duc", "Saint-Cyr-sur-Loire",
# "La Capelle-lès-Boulogne", "Lons-le-Saunier"...
# La continuation n'accepte que des suffixes à tiret (le, sur, lès...) ou un mot
# suivant débutant par une majuscule — sinon on avalerait toute la phrase.
_PROPER_NAMES = re.compile(
    r"[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÆŒÇ][a-zà-ÿ'’]+"
    r"(?:-[A-Za-zà-ÿ'’]+|\s+[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÆŒÇ][a-zà-ÿ'’]+)*"
)


def _cle(valeur: str | None) -> str:
    """Clé insensible casse/accents/tirets/apostrophes."""
    sans = "".join(
        c for c in unicodedata.normalize("NFD", valeur or "")
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[-'’\s]+", " ", sans.lower()).strip()


def _banque_tokens(banque: str | None) -> set[str]:
    return set(_cle(banque).split())


def candidats_communes(texte: str, banque: str | None) -> list[str]:
    """Extrait les noms propres plausibles comme communes, dans l'ordre du texte.

    Filtre les fragments qui appartiennent au nom de la banque et ceux qui ne
    sont manifestement pas des communes (régions, territoires, génériques).
    """
    btokens = _banque_tokens(banque)
    seen: set[str] = set()
    out: list[str] = []
    for m in _PROPER_NAMES.finditer(texte or ""):
        token = m.group(0).strip()
        cle = _cle(token)
        if not cle or cle in seen:
            continue
        # Ignore les fragments qui chevauchent le nom de la banque
        # ("La BNP Paribas", "Paribas"...).
        if btokens and (set(cle.split()) & btokens):
            continue
        if not validation.commune_publiable(token):
            continue
        seen.add(cle)
        out.append(token)
    return out


def commune_candidate(
    vigilance: dict,
    geocode_fn: Callable[..., dict | None],
) -> str | None:
    """Première commune candidate validée par la BAN (code INSEE réel)."""
    texte = f"{vigilance.get('titre','')} {vigilance.get('extrait','')}"
    for candidate in candidats_communes(texte, vigilance.get("banque")):
        try:
            geo = geocode_fn(candidate, vigilance.get("departement"))
        except Exception:
            continue
        if geo and geo.get("code_insee"):
            return candidate
    return None


def generer_requetes(
    vigilance: dict,
    geocode_fn: Callable[..., dict | None],
    max_queries: int | None = None,
) -> list[str]:
    """Génère les requêtes secondaires pour une vigilance, ou [] si trop faible."""
    banque = vigilance.get("banque")
    if not banque:
        return []
    commune = commune_candidate(vigilance, geocode_fn)
    if not commune:
        return []
    if max_queries is None:
        max_queries = config.VIGILANCE_REVIEW_MAX_QUERIES_PER_ITEM
    return query_builder.build_queries(
        banque, commune,
        departement=vigilance.get("departement"),
        max_queries=max_queries,
    )


def review_vigilance(
    vigilance: dict,
    *,
    search_fn: Callable[[str], list[dict]],
    extractor_fn: Callable[[dict], dict | None],
    geocode_fn: Callable[..., dict | None],
    max_queries: int | None = None,
) -> dict:
    """Exécute la revue secondaire d'une vigilance.

    Retourne un compte-rendu : queries_tried, new_urls, articles, closures.
    Best-effort : un provider en erreur n'interrompt jamais la revue.
    """
    result: dict = {"queries_tried": 0, "new_urls": [], "articles": 0, "closures": []}
    queries = generer_requetes(vigilance, geocode_fn, max_queries)
    result["queries_tried"] = len(queries)

    seen_urls: set[str] = set()
    articles: list[dict] = []
    for query in queries:
        try:
            trouves = search_fn(query) or []
        except Exception as exc:
            print(f"[vigilance_review] provider en erreur ({query}): {exc}")
            continue
        for art in trouves:
            url = (art.get("url") or "").strip()
            if url:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                result["new_urls"].append(url)
            articles.append(art)
    result["articles"] = len(articles)

    for art in articles:
        try:
            closure = extractor_fn(art)
        except Exception as exc:
            print(f"[vigilance_review] extraction en erreur: {exc}")
            continue
        if not closure:
            continue
        try:
            geo = geocode_fn(closure["commune"], closure.get("departement"))
        except Exception:
            geo = None
        if geo:
            closure["lat"] = closure.get("lat") or geo.get("lat")
            closure["lon"] = closure.get("lon") or geo.get("lon")
            if not closure.get("code_insee"):
                closure["code_insee"] = geo.get("code_insee")
            if not validation.departement_valide(closure.get("departement")):
                closure["departement"] = geo.get("departement")
        publiable, _raison = validation.fermeture_publiable(closure, geo)
        if publiable:
            closure["_source"] = {
                "url": art.get("url"), "titre": art.get("titre"),
                "source": art.get("source"), "date": art.get("date"),
            }
            result["closures"].append(closure)
    return result


def reviser_vigilances(
    conn,
    *,
    search_fn: Callable[..., list[dict]],
    extractor_fn: Callable[[dict], dict | None],
    geocode_fn: Callable[..., dict | None],
    min_score: int | None = None,
    max_per_run: int | None = None,
    max_queries: int | None = None,
    cooldown_days: int | None = None,
) -> dict:
    """Orchestre la revue des vigilances qualifiées et persiste les résultats.

    Sélectionne les vigilances d'un score suffisant non revues récemment, lance
    la revue secondaire, publie les fermetures obtenues et journalise chaque
    revue (table vigilance_reviews) pour éviter tout retraitement en boucle.
    """
    from backend import store

    if min_score is None:
        min_score = config.VIGILANCE_REVIEW_MIN_SCORE
    if max_per_run is None:
        max_per_run = config.VIGILANCE_REVIEW_MAX_PER_RUN
    if cooldown_days is None:
        cooldown_days = config.VIGILANCE_REVIEW_COOLDOWN_DAYS

    summary = {"reviewed": 0, "closures_created": 0, "new_urls": 0}
    selection = store.select_vigilances_a_reviser(
        conn, min_score, max_per_run, cooldown_days)
    for vig in selection:
        out = review_vigilance(
            vig, search_fn=search_fn, extractor_fn=extractor_fn,
            geocode_fn=geocode_fn, max_queries=max_queries)
        created = 0
        for closure in out["closures"]:
            src = closure.pop("_source", None)
            store.upsert_closure(conn, closure)
            if src and src.get("url"):
                store.add_source(conn, closure["id"], src)
            created += 1
        store.upsert_vigilance_review(conn, {
            "id": vig["id"],
            "review_status": "done",
            "queries_tried": out["queries_tried"],
            "new_urls_found": len(out["new_urls"]),
            "closures_created": created,
        })
        summary["reviewed"] += 1
        summary["closures_created"] += created
        summary["new_urls"] += len(out["new_urls"])
    return summary
