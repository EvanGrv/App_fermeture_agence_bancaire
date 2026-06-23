# run.py
import anthropic
import config
from backend import store, export, geocode, geojson, referentiel, controle, vigilance
from backend.pipeline import run_pipeline, ingest_closures
from backend.extractor import extract
from backend.collectors import google_news, gdelt, legifrance, local_feeds, official, sg_locator


def main():
    conn = store.init_db(config.DB_PATH)
    client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY
    cache_geo = {}

    collectors = [
        google_news.collect,
        local_feeds.collect,
        gdelt.collect,
        official.collect,
        legifrance.collect,
    ]
    recap = run_pipeline(
        conn,
        collectors,
        extractor_fn=lambda art: extract(art, client=client),
        geocoder_fn=lambda commune, dept: geocode.geocode_commune(
            commune, dept, cache=cache_geo),
        vigilance_fn=lambda art, raison: store.upsert_vigilance(
            conn, vigilance.depuis_article(art, raison)
        ) if vigilance.depuis_article(art, raison) else None,
    )
    # Fermetures SG nominativement vérifiées (localisateur officiel), géocodées
    # à l'adresse précise — Niveau 1, sans appel IA.
    geo_adr = lambda adr: geocode.geocode_adresse(adr, cache=cache_geo)
    sg_records = sg_locator.seed_closures() + sg_locator.crawled_closures(
        config.CACHE_DIR / "sg_crawl.json")
    n_sg = ingest_closures(conn, sg_records, geo_adr)
    branches = referentiel.fetch_osm_banques()
    for branche in branches:
        store.upsert_referentiel(conn, branche)
    n_vigilances_legifrance = vigilance.ingest_articles(
        conn,
        legifrance.collect(),
        raison="signal faible Légifrance sans agence nominative validée",
    )
    controles = 0
    for cid, banque, commune in conn.execute("SELECT id, banque, commune FROM closures"):
        statut_sirene = controle.confirmer_fermeture(banque, commune)
        store.upsert_controle_sirene(conn, cid, statut_sirene)
        controles += 1
    geojson.ensure_departements_geojson()
    export.export_json(conn, config.DATA_JSON)
    print("Récapitulatif presse:", recap)
    print("Fermetures SG vérifiées ingérées:", n_sg)
    print("Agences du référentiel OSM ingérées:", len(branches))
    print("Signaux de vigilance Légifrance:", n_vigilances_legifrance)
    print("Contrôles SIRENE effectués:", controles)
    print("Export écrit dans", config.DATA_JSON)


if __name__ == "__main__":
    main()
