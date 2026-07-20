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

import html
import re
import unicodedata
from typing import Callable

import config
from backend import query_builder, validation
from backend.dedup import closure_id, normalise_cle
from backend.extractor import normalise_banque

# Séquences de mots à majuscule (noms propres) : "Bar-le-Duc", "Saint-Cyr-sur-Loire",
# "La Capelle-lès-Boulogne", "Lons-le-Saunier"...
# La continuation n'accepte que des suffixes à tiret (le, sur, lès...) ou un mot
# suivant débutant par une majuscule — sinon on avalerait toute la phrase.
_PROPER_NAMES = re.compile(
    r"[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÆŒÇ][a-zà-ÿ'’]+"
    r"(?:-[A-Za-zà-ÿ'’]+|\s+[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÆŒÇ][a-zà-ÿ'’]+)*"
)

_FERMETURE_AGENCE_RE = re.compile(
    r"\b(fermeture|ferme|fermer|fermera|fermeront|fermé|fermée|ferment|"
    r"fermetures|suppression|supprime|regroupement)\b"
    r".{0,90}\b(agence|agences|banque|bancaire|guichet|succursale|bureau de poste|bureaux de poste)\b"
    r"|"
    r"\b(agence|agences|banque|bancaire|guichet|succursale|bureau de poste|bureaux de poste)\b"
    r".{0,90}\b(fermeture|ferme|fermer|fermera|fermeront|fermé|fermée|ferment|"
    r"fermetures|suppression|supprime|regroupement)\b",
    re.IGNORECASE | re.DOTALL,
)

_POSTAL_CLOSURE_RE = re.compile(
    r"\b(fermeture|ferme|fermer|fermera|fermeront|fermé|fermée|ferment|"
    r"fermetures|suppression|supprime)\b.{0,110}\b(bureau de poste|bureaux de poste)\b"
    r"|"
    r"\b(bureau de poste|bureaux de poste)\b.{0,110}\b(fermeture|ferme|fermer|"
    r"fermera|fermeront|fermé|fermée|ferment|fermetures|suppression|supprime)\b",
    re.IGNORECASE | re.DOTALL,
)

_HINT_RE = re.compile(
    r"\b(?:dans|en|du|de|des|d'|l')\s+"
    r"([A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+){0,3})"
)

_EXCLUSION_FALLBACK_RE = re.compile(
    r"fermeture temporaire|temporairement ferm[ée]e?|travaux|r[ée]nov|rouvre|"
    r"agence immobili[èe]re|transporteur|"
    r"guichet automatique|distributeur automatique|DAB|gr[èe]ve|syndicat|"
    r"manifestation|craignent|liste|votre ville|plusieurs agences|"
    r"\b\d+\s+agences\b|fermetures d[’']agences|fermeture d[’']agences",
    re.IGNORECASE,
)

_POSTAL_PARTNER_RE = re.compile(
    r"agence postale communale|relais poste|relais postal|point relais",
    re.IGNORECASE,
)
_POSTAL_BANKING_RE = re.compile(
    r"banque postale|services? financiers?|services? bancaires?|conseiller bancaire|"
    r"retrait d[’']esp[eè]ces|d[ée]p[oô]t d[’']esp[eè]ces|gestion de comptes?",
    re.IGNORECASE,
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


def _texte_candidats(texte: str | None) -> str:
    """Nettoie HTML/URLs avant extraction des noms propres.

    Les extraits Google News contiennent souvent un `<a href="...">` dont l'URL
    encodée produit des faux candidats ("Szd", "Zksz"...). On garde le libellé
    visible de l'article, pas les attributs HTML.
    """
    cleaned = html.unescape(texte or "")
    cleaned = re.sub(r"<[^>]+>", ". ", cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"\s+-\s+[^.]+$", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def candidats_communes(texte: str, banque: str | None) -> list[str]:
    """Extrait les noms propres plausibles comme communes, dans l'ordre du texte.

    Filtre les fragments qui appartiennent au nom de la banque et ceux qui ne
    sont manifestement pas des communes (régions, territoires, génériques).
    """
    btokens = _banque_tokens(banque)
    seen: set[str] = set()
    out: list[str] = []
    for m in _PROPER_NAMES.finditer(_texte_candidats(texte)):
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


def signal_fermeture_agence(texte: str) -> bool:
    """True si le texte ressemble à une fermeture d'agence bancaire."""
    return bool(_FERMETURE_AGENCE_RE.search(texte or ""))


def signal_fermeture_bureau_poste(texte: str) -> bool:
    """True si le texte ressemble à une fermeture de bureau de poste."""
    return bool(_POSTAL_CLOSURE_RE.search(texte or ""))


def _banque_presente(texte: str, banque: str | None) -> bool:
    banque_norm = normalise_banque(banque or "")
    cle_texte = normalise_cle(texte or "").replace("'", " ")
    cle_banque = normalise_cle(banque_norm).replace("'", " ")
    variantes = {cle_banque}
    if cle_banque == "bnp paribas":
        variantes.add("bnp")
    if cle_banque == "caisse d epargne":
        variantes.add("caisse epargne")
    if cle_banque == "la banque postale":
        variantes.add("banque postale")
    if cle_banque == "credit mutuel":
        variantes.add("cmb")
    return any(re.search(rf"\b{re.escape(v)}\b", cle_texte) for v in variantes if v)


def _hint_recherche(vigilance: dict) -> str | None:
    """Indice non-commune pour retrouver l'article source (département/région)."""
    texte = f"{vigilance.get('titre','')} {vigilance.get('extrait','')}"
    for m in _HINT_RE.finditer(texte):
        hint = m.group(1).strip(" .,:;")
        if validation.commune_publiable(hint):
            return hint
    return vigilance.get("departement")


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


def communes_candidates_validees(
    article: dict,
    geocode_fn: Callable[..., dict | None],
    *,
    banque: str | None,
    departement: str | None = None,
) -> list[tuple[str, dict]]:
    """Communes candidates validées par BAN/OSM, dédupliquées."""
    titre = article.get("titre") or ""
    textes = [titre] if titre else []
    out: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for texte in textes:
        for candidate in candidats_communes(texte, banque):
            try:
                geo = geocode_fn(candidate, departement or article.get("departement"))
            except Exception:
                continue
            if not geo or not geo.get("code_insee"):
                continue
            cle = geo.get("code_insee") or _cle(candidate)
            if cle in seen:
                continue
            seen.add(cle)
            out.append((candidate, geo))
        if out:
            return out
    return out


def _titre_localise_singulier(titre: str, banque: str | None, commune: str) -> bool:
    """Garde uniquement les titres qui parlent d'une agence locale précise."""
    titre_clean = _texte_candidats(titre)
    if not titre_clean or commune not in titre_clean:
        return False
    if _EXCLUSION_FALLBACK_RE.search(titre_clean):
        return False
    banque_pat = re.escape(banque or "")
    commune_pat = re.escape(commune)
    patterns = [
        rf"\bagence\s+(?:du|de la|de l'|d'|{banque_pat})?.{{0,80}}{commune_pat}",
        rf"{commune_pat}.{{0,100}}\bagence\b.{{0,80}}\bferme",
        rf"\bfermeture\b.{{0,80}}\bagence\b.{{0,100}}{commune_pat}",
        rf"\b{banque_pat}\b.{{0,80}}\bferme\b.{{0,80}}\bagence\b.{{0,80}}{commune_pat}",
        rf"\b{banque_pat}\b.{{0,40}}\b(?:de|d'|à)\s+{commune_pat}.{{0,60}}\b(?:va\s+)?fermer\b",
    ]
    return any(re.search(p, titre_clean, re.IGNORECASE) for p in patterns)


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
    if max_queries is None:
        max_queries = config.VIGILANCE_REVIEW_MAX_QUERIES_PER_ITEM
    if commune:
        return query_builder.build_queries(
            banque, commune,
            departement=vigilance.get("departement"),
            max_queries=max_queries,
        )
    texte = f"{vigilance.get('titre','')} {vigilance.get('extrait','')}"
    if not (signal_fermeture_agence(texte) or signal_fermeture_bureau_poste(texte)):
        return []
    return query_builder.build_discovery_queries(
        banque,
        hint=_hint_recherche(vigilance),
        max_queries=max_queries,
    )


def fermeture_depuis_signal(
    article: dict,
    *,
    banque: str | None,
    geocode_fn: Callable[..., dict | None],
    departement: str | None = None,
) -> dict | None:
    """Fallback sans IA : publie seulement un signal mono-commune géocodé.

    Sert pour les alertes dont le titre est déjà explicite ("l'agence X de Y va
    fermer") mais où l'extraction IA ou le fulltext ne donnent rien.
    """
    texte = f"{article.get('titre','')} {article.get('texte','')} {article.get('extrait','')}"
    is_lbp = normalise_banque(banque or "") == "La Banque Postale"
    is_postal = signal_fermeture_bureau_poste(texte)
    if not banque or not (signal_fermeture_agence(texte) or (is_lbp and is_postal)):
        return None
    if _EXCLUSION_FALLBACK_RE.search(texte):
        return None
    if is_lbp and _POSTAL_PARTNER_RE.search(texte) and not _POSTAL_BANKING_RE.search(texte):
        return None
    if not _banque_presente(texte, banque) and not (is_lbp and is_postal):
        return None
    candidates = communes_candidates_validees(
        article, geocode_fn, banque=banque, departement=departement)
    if len(candidates) != 1:
        return None
    commune, geo = candidates[0]
    banque_norm = normalise_banque(banque)
    if is_lbp and is_postal:
        titre_clean = _texte_candidats(article.get("titre") or "")
        if commune not in titre_clean or not signal_fermeture_bureau_poste(titre_clean):
            return None
    elif not _titre_localise_singulier(article.get("titre") or "", banque_norm, commune):
        return None
    commune_pub = geo.get("commune") or commune
    futur = re.search(
        r"\b(va|vont|devrait|devraient|bient[oô]t|prochainement|fin\s+\w+|"
        r"prévue|prévu|sera|seront)\b",
        texte,
        re.IGNORECASE,
    )
    closure = {
        "id": closure_id(banque_norm, commune_pub, "fermeture"),
        "banque": banque_norm,
        "commune": commune_pub,
        "code_insee": geo.get("code_insee"),
        "departement": geo.get("departement") or departement or article.get("departement"),
        "type": "fermeture",
        "date_annonce": article.get("date") or None,
        "date_fermeture": None,
        "statut": "projet",
        "statut_temporel": "a_venir" if futur else "inconnu",
        "date_fermeture_approx": 0,
        "fiabilite": min(3, int(article.get("score") or 3)),
        "lat": geo.get("lat"),
        "lon": geo.get("lon"),
        "citation": article.get("titre") or article.get("texte") or article.get("url") or "",
    }
    publiable, _raison = validation.fermeture_publiable(closure, geo)
    return closure if publiable else None


def _closure_natural_key(closure: dict) -> tuple[str, str, str]:
    return (
        normalise_cle(closure.get("banque") or ""),
        str(closure.get("code_insee") or normalise_cle(closure.get("commune") or "")),
        closure.get("type") or "fermeture",
    )


def _append_closure_dedup(result: dict, closure: dict) -> None:
    """Ajoute une fermeture en évitant les doublons article origine/provider."""
    key = _closure_natural_key(closure)
    for idx, existing in enumerate(result["closures"]):
        if _closure_natural_key(existing) != key:
            continue
        if (closure.get("fiabilite") or 0) > (existing.get("fiabilite") or 0):
            result["closures"][idx] = closure
        return
    result["closures"].append(closure)


def review_vigilance(
    vigilance: dict,
    *,
    search_fn: Callable[[str], list[dict]],
    extractor_fn: Callable[[dict], dict | None] | None,
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
    if vigilance.get("url") or vigilance.get("titre"):
        articles.append({
            "titre": vigilance.get("titre") or "",
            "texte": vigilance.get("extrait") or "",
            "extrait": vigilance.get("extrait") or "",
            "url": vigilance.get("url") or "",
            "date": vigilance.get("date"),
            "source": vigilance.get("source"),
            "departement": vigilance.get("departement"),
            "score": vigilance.get("score"),
        })
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
        closure = None
        if extractor_fn is not None:
            try:
                closure = extractor_fn(art)
            except Exception as exc:
                print(f"[vigilance_review] extraction en erreur: {exc}")
                closure = None
        if not closure:
            closure = fermeture_depuis_signal(
                art,
                banque=vigilance.get("banque"),
                geocode_fn=geocode_fn,
                departement=vigilance.get("departement"),
            )
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
            _append_closure_dedup(result, closure)
    return result


def reviser_vigilances(
    conn,
    *,
    search_fn: Callable[..., list[dict]],
    extractor_fn: Callable[[dict], dict | None] | None,
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
