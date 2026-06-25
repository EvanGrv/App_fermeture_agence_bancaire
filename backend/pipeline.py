# backend/pipeline.py
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from backend import prefilter, store, validation
from backend.fulltext import fetch_text


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
            _enrich = enrich_fn if enrich_fn is not None else fetch_text
            texte = art.get("texte") or ""
            if url and len(texte) < 400:
                try:
                    texte_complet = _enrich(url)
                    if texte_complet:
                        art["texte"] = (texte + "\n\n" + texte_complet)[:6000]
                except Exception:
                    pass
            try:
                resultat = extractor_fn(art)
            except Exception as exc:
                print(f"[pipeline] extraction en erreur ({url}): {exc}")
                continue
            if url:
                store.mark_url_seen(conn, url)
            if resultat is None:
                if vigilance_fn and vigilance_fn(art, "article pertinent sans fermeture publiable"):
                    recap["vigilances"] += 1
                continue
            recap["extraits"] += 1
            geo = geocoder_fn(resultat["commune"], resultat.get("departement"))
            if geo:
                resultat["lat"] = geo.get("lat")
                resultat["lon"] = geo.get("lon")
                if not validation.departement_valide(resultat.get("departement")):
                    resultat["departement"] = geo.get("departement")
                if not resultat.get("code_insee"):
                    resultat["code_insee"] = geo.get("code_insee")
            publiable, raison = validation.fermeture_publiable(resultat, geo)
            if not publiable:
                recap["rejets_validation"] += 1
                if vigilance_fn and vigilance_fn(art, f"fermeture non publiée: {raison}"):
                    recap["vigilances"] += 1
                continue
            store.upsert_closure(conn, resultat)
            store.add_source(conn, resultat["id"], {
                "url": url, "titre": art.get("titre"),
                "source": art.get("source"), "date": art.get("date"),
            })
            recap["fermetures"] += 1
        if progress_fn:
            progress_fn(f"{collector_name}: terminé", end_pct)
    return recap
