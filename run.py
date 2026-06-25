# run.py
import argparse
import math
import os
from datetime import date, timedelta

import anthropic
import config
from backend import store, export, geocode, geojson, referentiel, controle, vigilance, audit
from backend.pipeline import run_pipeline, ingest_closures
from backend.extractor import extract
from backend.collectors import google_news, gdelt, legifrance, local_feeds, official, sg_locator


def progress(label: str, percent: int) -> None:
    print(f"[progress] {percent} {label}", flush=True)


def _since_from_args(args) -> str | None:
    provided = [args.since is not None, args.lookback_days is not None, args.lookback_months is not None]
    if sum(provided) > 1:
        raise SystemExit("Utiliser un seul paramètre parmi --since, --lookback-days ou --lookback-months.")
    if args.since:
        date.fromisoformat(args.since)
        return args.since
    if args.lookback_days is not None:
        if args.lookback_days < 1:
            raise SystemExit("--lookback-days doit être positif.")
        return (date.today() - timedelta(days=args.lookback_days)).isoformat()
    if args.lookback_months is not None:
        if args.lookback_months < 1:
            raise SystemExit("--lookback-months doit être positif.")
        return (date.today() - timedelta(days=args.lookback_months * 30)).isoformat()
    return (date.today() - timedelta(days=config.LOOKBACK_MONTHS_DEFAULT * 30)).isoformat()


def _configure_collection_window(since_date: str | None) -> dict:
    if not since_date:
        return {
            "since_date": None,
            "google_news_when": config.GOOGLE_NEWS_WHEN,
            "gdelt_timespan": gdelt._TIMESPAN,
        }
    days = max(1, (date.today() - date.fromisoformat(since_date)).days + 1)
    config.GOOGLE_NEWS_WHEN = f"{days}d"
    gdelt._TIMESPAN = f"{math.ceil(days / 30)}m" if days >= 30 else f"{days}d"
    return {
        "since_date": since_date,
        "google_news_when": config.GOOGLE_NEWS_WHEN,
        "gdelt_timespan": gdelt._TIMESPAN,
    }


def main(since_date: str | None = None):
    progress("Configuration de la fenêtre de collecte", 5)
    window = _configure_collection_window(since_date)
    conn = store.init_db(config.DB_PATH)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY absente. Vérifie le fichier .env ou exporte la variable "
            "avant de relancer la collecte."
        )
    client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY
    cache_geo = {}

    progress("Collecte presse et extraction IA", 15)
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
        since_date=since_date,
        progress_fn=progress,
    )
    progress("Ingestion des fermetures SG vérifiées", 55)
    # Fermetures SG nominativement vérifiées (localisateur officiel), géocodées
    # à l'adresse précise — Niveau 1, sans appel IA.
    geo_adr = lambda adr: geocode.geocode_adresse(adr, cache=cache_geo)
    sg_records = sg_locator.seed_closures() + sg_locator.crawled_closures(
        config.CACHE_DIR / "sg_crawl.json")
    n_sg = ingest_closures(conn, sg_records, geo_adr)
    progress("Chargement du référentiel agences", 65)
    branches = referentiel.fetch_osm_banques()
    for branche in branches:
        store.upsert_referentiel(conn, branche)
    total_referentiel = conn.execute("SELECT COUNT(*) FROM referentiel").fetchone()[0]
    progress("Signaux de vigilance Légifrance", 75)
    n_vigilances_legifrance = vigilance.ingest_articles(
        conn,
        legifrance.collect(),
        raison="signal faible Légifrance sans agence nominative validée",
    )
    progress("Contrôles SIRENE", 85)
    controles = 0
    for cid, banque, commune in conn.execute("SELECT id, banque, commune FROM closures"):
        statut_sirene = controle.confirmer_fermeture(banque, commune)
        store.upsert_controle_sirene(conn, cid, statut_sirene)
        controles += 1
    progress("Export des fichiers front", 95)
    geojson.ensure_departements_geojson()
    export.export_json(conn, config.DATA_JSON)
    export.export_fermetures_csv(conn, config.EXPORT_DIR / "fermetures_nettoyees.csv")
    audit_findings = audit.write_reports(config.DATA_JSON, config.EXPORT_DIR)
    progress("Terminé", 100)
    print("Fenêtre de collecte:", window)
    print("Récapitulatif presse:", recap)
    print("Fermetures SG vérifiées ingérées:", n_sg)
    print("Agences du référentiel OSM récupérées ce run:", len(branches))
    print("Agences du référentiel disponibles dans l'app:", total_referentiel)
    print("Signaux de vigilance Légifrance:", n_vigilances_legifrance)
    print("Contrôles SIRENE effectués:", controles)
    print("Alertes audit extraction:", len(audit_findings))
    print("Export écrit dans", config.DATA_JSON)
    print("Tableau fermetures nettoyées:", config.EXPORT_DIR / "fermetures_nettoyees.csv")
    return {
        "window": window,
        "recap": recap,
        "sg": n_sg,
        "referentiel": len(branches),
        "referentiel_total": total_referentiel,
        "vigilances_legifrance": n_vigilances_legifrance,
        "controles": controles,
        "audit_findings": len(audit_findings),
        "export": str(config.DATA_JSON),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Lance la veille presse fermetures d'agences bancaires.")
    parser.add_argument("--since", help="Date de départ exacte au format YYYY-MM-DD.")
    parser.add_argument("--lookback-days", type=int, help="Nombre de jours à remonter depuis aujourd'hui.")
    parser.add_argument("--lookback-months", type=int, help="Nombre de mois approximatif à remonter depuis aujourd'hui.")
    return parser.parse_args()


if __name__ == "__main__":
    main(_since_from_args(parse_args()))
