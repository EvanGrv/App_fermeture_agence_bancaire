# backend/pipeline.py
import hashlib
import config
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from backend import (
    commune_normalize,
    context_builder,
    extraction_guard,
    extractor,
    ingest_map,
    prefilter,
    store,
    validation,
    vigilance_review,
)
from backend.fulltext import fetch_text, fetch_article
from backend.extraction_cache import extract_cached_with_status


def _parse_article_date(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.date()


def _parse_since(since_date: str | None):
    if not since_date:
        return None
    return date.fromisoformat(since_date)


def ingest_closures(conn, closures, geocoder_adresse_fn) -> int:
    """Stocke des fermetures déjà structurées (ex. seed localisateur SG),
    géocodées à l'ADRESSE précise. Retourne le nombre stocké."""
    n = 0
    for c in closures:
        adresse = c.pop("_adresse", None)
        source_url = c.pop("_source_url", None)
        geo = geocoder_adresse_fn(adresse) if adresse else None
        if geo:
            c["lat"] = geo.get("lat")
            c["lon"] = geo.get("lon")
            if not c.get("code_insee"):
                c["code_insee"] = geo.get("code_insee")
            if not c.get("departement"):
                c["departement"] = geo.get("departement")
        store.upsert_closure(conn, c)
        if source_url:
            store.add_source(conn, c["id"], {
                "url": source_url, "titre": c.get("citation"),
                "source": "SG (localisateur officiel)", "date": c.get("date_fermeture"),
            })
        n += 1
    return n


def _ingest_closure(conn, resultat, art, url, geocoder_fn, recap):
    geo = geocoder_fn(resultat["commune"], resultat.get("departement"))
    if geo:
        resultat["lat"] = geo.get("lat")
        resultat["lon"] = geo.get("lon")
        if not validation.departement_valide(resultat.get("departement")):
            resultat["departement"] = geo.get("departement")
        if not resultat.get("code_insee"):
            resultat["code_insee"] = geo.get("code_insee")
        decision = extraction_guard.evaluate(
            resultat, art, geo, geocode_fn=geocoder_fn
        )
        if not decision.accepted:
            recap["rejets_validation"] += 1
            return False, decision.reason
        # Rattache à la commune administrative (BAN) et conserve la
        # localisation d'agence d'origine (ex. Coëtquidan -> Guer).
        resultat = commune_normalize.appliquer(resultat, geo)
    else:
        decision = extraction_guard.evaluate(
            resultat, art, geo, geocode_fn=geocoder_fn
        )
        if not decision.accepted:
            recap["rejets_validation"] += 1
            return False, decision.reason
    publiable, raison = validation.fermeture_publiable(resultat, geo)
    if not publiable:
        recap["rejets_validation"] += 1
        return False, raison
    store.upsert_closure(conn, resultat)
    store.add_source(conn, resultat["id"], {
        "url": url, "titre": art.get("titre"),
        "source": art.get("source"), "date": art.get("date"),
    })
    recap["fermetures"] += 1
    return True, None


def _persist_unlocated_closure(conn, closure, art, url, raison):
    key = "|".join([
        url or "",
        closure.get("banque") or "",
        closure.get("commune") or "",
        closure.get("type") or "",
    ])
    store.upsert_closure_unlocated(conn, {
        "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
        "banque": closure.get("banque"),
        "commune": closure.get("commune"),
        "departement": closure.get("departement"),
        "type": closure.get("type"),
        "date_fermeture": closure.get("date_fermeture"),
        "statut": closure.get("statut"),
        "statut_temporel": closure.get("statut_temporel"),
        "fiabilite": closure.get("fiabilite"),
        "citation": closure.get("citation"),
        "url": url or None,
        "titre": art.get("titre"),
        "source": art.get("source"),
        "date": art.get("date"),
        "raison": raison,
    })


def _persist_structured_signals(conn, result, art, url):
    for signal in result.get("department_signals") or []:
        key = "|".join([
            url or "",
            signal.get("bank") or "",
            signal.get("departement") or "",
            str(signal.get("count") or ""),
        ])
        store.upsert_department_signal(conn, {
            "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
            "banque": signal.get("bank"),
            "departement": signal.get("departement"),
            "count": signal.get("count"),
            "communes_mentioned": ", ".join(signal.get("communes_mentioned") or []),
            "confidence": signal.get("confidence"),
            "evidence": signal.get("evidence"),
            "url": url or None,
            "titre": art.get("titre"),
            "source": art.get("source"),
            "date": art.get("date"),
        })
    for signal in result.get("vague_signals") or []:
        key = "|".join([
            url or "",
            signal.get("bank") or "",
            signal.get("scope") or "",
            str(signal.get("count") or ""),
        ])
        store.upsert_vague_signal(conn, {
            "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
            "banque": signal.get("bank"),
            "scope": signal.get("scope"),
            "count": signal.get("count"),
            "confidence": signal.get("confidence"),
            "evidence": signal.get("evidence"),
            "url": url or None,
            "titre": art.get("titre"),
            "source": art.get("source"),
            "date": art.get("date"),
        })


def _ingest_postal_fallback(
    conn,
    art,
    url,
    geocoder_fn,
    recap,
    since_date,
) -> bool:
    """Publie les fermetures postales explicites sans dépendre de l'IA."""
    if not prefilter.is_postal_closure_candidate(art):
        return False
    closures = vigilance_review.fermetures_depuis_signal(
        art,
        banque="La Banque Postale",
        geocode_fn=geocoder_fn,
        departement=art.get("departement"),
    )
    if not closures:
        return False
    aujourdhui = date.today().isoformat()
    publications = 0
    for closure in closures:
        if not extractor._retenir_fermeture(
            closure["statut_temporel"],
            closure.get("date_fermeture"),
            since_date,
            aujourdhui,
        ):
            _persist_unlocated_closure(
                conn, closure, art, url, "hors fenêtre temporelle"
            )
            continue
        recap["extraits"] += 1
        ok, raison = _ingest_closure(conn, closure, art, url, geocoder_fn, recap)
        if ok:
            publications += 1
        elif raison:
            _persist_unlocated_closure(conn, closure, art, url, raison)
    if publications and url:
        store.delete_vigilance_by_url(conn, url)
    return True


def ingest_postal_vigilance_backlog(
    conn,
    articles,
    geocoder_fn,
    since_date: str | None = None,
) -> dict:
    """Résout sans IA les vigilances postales déjà présentes en base."""
    recap = {
        "articles": len(articles),
        "extraits": 0,
        "fermetures": 0,
        "rejets_validation": 0,
    }
    for art in articles:
        url = art.get("url") or ""
        if _ingest_postal_fallback(
            conn, art, url, geocoder_fn, recap, since_date
        ):
            if url:
                store.mark_url_seen(conn, url)
    return recap


def run_pipeline(
    conn,
    collectors,
    extractor_fn,
    geocoder_fn,
    vigilance_fn=None,
    enrich_fn=None,
    since_date: str | None = None,
    progress_fn=None,
) -> dict:
    since = _parse_since(since_date)
    recap = {
        "articles": 0,
        "hors_periode": 0,
        "filtres": 0,
        "extraits": 0,
        "fermetures": 0,
        "vigilances": 0,
        "rejets_validation": 0,
    }
    total_collectors = max(1, len(collectors))
    for collector_index, collect in enumerate(collectors):
        collector_name = getattr(collect, "__name__", "collecteur")
        start_pct = 15 + int((collector_index / total_collectors) * 40)
        end_pct = 15 + int(((collector_index + 1) / total_collectors) * 40)
        if progress_fn:
            progress_fn(f"Collecte {collector_name}", start_pct)
        try:
            articles = collect()
        except Exception as exc:
            print(f"[pipeline] collecteur en erreur: {exc}")
            continue
        total_articles = max(1, len(articles))
        for article_index, art in enumerate(articles):
            if progress_fn and (article_index == 0 or article_index % 10 == 0):
                pct = start_pct + int((article_index / total_articles) * max(1, end_pct - start_pct))
                progress_fn(
                    f"{collector_name}: article {article_index + 1}/{len(articles)}",
                    min(end_pct, pct),
                )
            recap["articles"] += 1
            art_date = _parse_article_date(art.get("date") or "")
            if since and art_date and art_date < since:
                recap["hors_periode"] += 1
                continue
            url = art.get("url") or ""
            if url and store.is_url_seen(conn, url):
                continue
            if not prefilter.is_relevant(art):
                if url:
                    store.mark_url_seen(conn, url)
                continue
            recap["filtres"] += 1
            _enrich = enrich_fn if enrich_fn is not None else (
                lambda u: fetch_article(u, conn=conn).get("fulltext") or "")
            texte = art.get("texte") or ""
            if url:
                try:
                    texte_complet = _enrich(url)
                    if texte_complet:
                        art["texte"] = (texte + "\n\n" + texte_complet)[:20000]
                except Exception:
                    pass
            pf = prefilter.analyse(art)
            pf.compact_context = context_builder.build_compact_context(art, pf)
            if pf.score <= config.PREFILTER_MIN_SCORE:
                if url:
                    store.mark_url_seen(conn, url)
                if vigilance_fn and vigilance_fn(art, f"score préfiltre bas ({pf.score})"):
                    recap["vigilances"] += 1
                continue
            fallback_art = {**art, "score": pf.score}
            if _ingest_postal_fallback(
                conn,
                fallback_art,
                url,
                geocoder_fn,
                recap,
                since_date,
            ):
                if url:
                    store.mark_url_seen(conn, url)
                continue
            art["texte"] = pf.compact_context
            try:
                resultat, extraction_status = extract_cached_with_status(art, extractor_fn, conn)
            except Exception as exc:
                print(f"[pipeline] extraction en erreur ({url}): {exc}")
                continue
            if extraction_status in {"error", "error_skip"}:
                continue
            if url:
                store.mark_url_seen(conn, url)
            if resultat is None:
                if vigilance_fn and vigilance_fn(art, "article pertinent sans fermeture publiable"):
                    recap["vigilances"] += 1
                continue
            aujourdhui = date.today().isoformat()
            _persist_structured_signals(conn, resultat, art, url)
            closures_map, signal_vigilance = ingest_map.map_result(resultat, art, aujourdhui)
            publications = 0
            rejets = []
            for closure in closures_map:
                if not extractor._retenir_fermeture(
                    closure["statut_temporel"],
                    closure.get("date_fermeture"),
                    since_date,
                    aujourdhui,
                ):
                    rejets.append("hors fenêtre temporelle")
                    _persist_unlocated_closure(conn, closure, art, url, "hors fenêtre temporelle")
                    continue
                recap["extraits"] += 1
                ok, raison = _ingest_closure(conn, closure, art, url, geocoder_fn, recap)
                if ok:
                    publications += 1
                elif raison:
                    rejets.append(raison)
                    _persist_unlocated_closure(conn, closure, art, url, raison)
            if signal_vigilance:
                store.upsert_vigilance(conn, signal_vigilance)
                recap["vigilances"] += 1
            elif publications == 0:
                raison = (
                    "fermeture non publiée: " + "; ".join(r for r in rejets if r)
                    if rejets else "article pertinent sans fermeture publiable"
                )
                if vigilance_fn and vigilance_fn(art, raison):
                    recap["vigilances"] += 1
        if progress_fn:
            progress_fn(f"{collector_name}: terminé", end_pct)
    return recap
