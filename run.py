# run.py
import anthropic
import config
from backend import store, export, geocode, geojson
from backend.pipeline import run_pipeline
from backend.extractor import extract
from backend.collectors import google_news, gdelt, local_feeds, official


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
    geojson.ensure_departements_geojson()
    export.export_json(conn, config.DATA_JSON)
    print("Récapitulatif:", recap)
    print("Export écrit dans", config.DATA_JSON)


if __name__ == "__main__":
    main()
