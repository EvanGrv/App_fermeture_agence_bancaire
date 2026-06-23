# run.py
import anthropic
import config
from backend import store, export, geocode, geojson
from backend.pipeline import run_pipeline, ingest_closures
from backend.extractor import extract
from backend.collectors import google_news, gdelt, local_feeds, official, sg_locator


def main():
    conn = store.init_db(config.DB_PATH)
    client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY
    cache_geo = {}

    collectors = [google_news.collect, local_feeds.collect, gdelt.collect, official.collect]
    recap = run_pipeline(
        conn,
        collectors,
        extractor_fn=lambda art: extract(art, client=client),
        geocoder_fn=lambda commune, dept: geocode.geocode_commune(
            commune, dept, cache=cache_geo),
    )
    # Fermetures SG nominativement vérifiées (localisateur officiel), géocodées
    # à l'adresse précise — Niveau 1, sans appel IA.
    n_sg = ingest_closures(
        conn, sg_locator.seed_closures(),
        lambda adr: geocode.geocode_adresse(adr, cache=cache_geo),
    )
    geojson.ensure_departements_geojson()
    export.export_json(conn, config.DATA_JSON)
    print("Récapitulatif presse:", recap)
    print("Fermetures SG vérifiées ingérées:", n_sg)
    print("Export écrit dans", config.DATA_JSON)


if __name__ == "__main__":
    main()
