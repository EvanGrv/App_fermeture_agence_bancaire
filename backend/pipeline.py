# backend/pipeline.py
from backend import prefilter, store


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


def run_pipeline(conn, collectors, extractor_fn, geocoder_fn) -> dict:
    recap = {"articles": 0, "filtres": 0, "extraits": 0, "fermetures": 0}
    for collect in collectors:
        try:
            articles = collect()
        except Exception as exc:
            print(f"[pipeline] collecteur en erreur: {exc}")
            continue
        for art in articles:
            recap["articles"] += 1
            url = art.get("url") or ""
            if url and store.is_url_seen(conn, url):
                continue
            if not prefilter.is_relevant(art):
                if url:
                    store.mark_url_seen(conn, url)
                continue
            recap["filtres"] += 1
            try:
                resultat = extractor_fn(art)
            except Exception as exc:
                print(f"[pipeline] extraction en erreur ({url}): {exc}")
                continue
            if url:
                store.mark_url_seen(conn, url)
            if resultat is None:
                continue
            recap["extraits"] += 1
            geo = geocoder_fn(resultat["commune"], resultat.get("departement"))
            if geo:
                resultat["lat"] = geo.get("lat")
                resultat["lon"] = geo.get("lon")
                if not resultat.get("departement"):
                    resultat["departement"] = geo.get("departement")
                if not resultat.get("code_insee"):
                    resultat["code_insee"] = geo.get("code_insee")
            store.upsert_closure(conn, resultat)
            store.add_source(conn, resultat["id"], {
                "url": url, "titre": art.get("titre"),
                "source": art.get("source"), "date": art.get("date"),
            })
            recap["fermetures"] += 1
    return recap
