# backend/pipeline.py
from backend import prefilter, store


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
