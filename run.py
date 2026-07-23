# run.py
import argparse
import math
import os
from datetime import date, timedelta

import anthropic
import config
from backend import (
    audit,
    controle,
    export,
    extractor as extractor_module,
    extraction_guard,
    geocode,
    geojson,
    ingest_map,
    openai_fallback,
    referentiel,
    store,
    vigilance,
)
from backend.pipeline import run_pipeline, ingest_closures, ingest_postal_vigilance_backlog
from backend.extractor import extract, extract_structured
from backend.collectors import (
    common_crawl, event_registry, google_news, gdelt, legifrance, local_feeds,
    mediacloud, official, sg_locator, web_search, postal_web, postal_history,
    laposte_open_data,
)
from backend import drilldown, vigilance_review, seed
from backend.fulltext import fetch_text
from backend.search_providers import registry as search_registry


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


def _build_ai_extractors(since_date: str | None = None) -> dict:
    """Construit les extracteurs du fournisseur IA sélectionné."""
    provider = config.EXTRACTION_PROVIDER
    if provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit(
                "OPENAI_API_KEY absente alors que EXTRACTION_PROVIDER=openai."
            )

        def structured(article):
            return openai_fallback.extract_openai_structured(
                article, date.today().isoformat()
            ).model_dump()

        def review(article):
            aujourdhui = date.today().isoformat()
            result = openai_fallback.extract_openai_structured(
                article, aujourdhui
            ).model_dump()
            closures, _signal = ingest_map.map_result(result, article, aujourdhui)
            for closure in closures:
                if extractor_module._retenir_fermeture(
                    closure["statut_temporel"],
                    closure.get("date_fermeture"),
                    since_date,
                    aujourdhui,
                ):
                    return closure
            return None

        return {"provider": provider, "structured": structured, "review": review}

    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit(
                "ANTHROPIC_API_KEY absente alors que EXTRACTION_PROVIDER=anthropic."
            )
        client = anthropic.Anthropic()
        return {
            "provider": provider,
            "structured": lambda article: extract_structured(
                article, client=client
            ).model_dump(),
            "review": lambda article: extract(
                article, client=client, floor=since_date
            ),
        }

    raise SystemExit(
        f"EXTRACTION_PROVIDER invalide: {provider!r} (attendu: openai ou anthropic)."
    )


def main(since_date: str | None = None):
    progress("Configuration de la fenêtre de collecte", 5)
    window = _configure_collection_window(since_date)
    conn = store.init_db(config.DB_PATH)
    lbp_quarantine = extraction_guard.quarantine_existing_lbp(conn)
    lbp_before = {
        row[0] for row in conn.execute(
            "SELECT id FROM closures WHERE banque='La Banque Postale'"
        )
    }
    ai = _build_ai_extractors(since_date)
    cache_geo = {}
    geo_commune = lambda c, d=None: geocode.geocode_commune_ou_lieu(
        c, d, cache=cache_geo
    )

    postal_requeued = store.requeue_postal_articles(
        conn, "postal-deterministic-fallback-v1"
    )
    postal_backlog = store.list_postal_vigilance_articles(conn)
    postal_backfill = ingest_postal_vigilance_backlog(
        conn, postal_backlog, geo_commune, since_date
    )

    progress("Synchronisation du réseau officiel La Poste", 10)
    postal_sync = laposte_open_data.sync_official_network(conn)

    progress("Collecte presse et extraction IA", 15)
    # Passe descendante : détecter les articles de plan multi-agences et générer des
    # requêtes ciblées commune par commune. Guarded : une erreur ici ne bloque pas le run.
    drill_queries: list[str] = []
    plan_articles: list[dict] = []
    try:
        plan_articles = google_news.collect(queries=drilldown.PLAN_SCAN_QUERIES)
        drill_queries = drilldown.requetes_depuis_articles(
            plan_articles, geo_commune
        )
    except Exception as _drill_exc:
        print(f"[drilldown] scan échoué, passage sans drill-down : {_drill_exc}")

    def collect_mediacloud():
        return mediacloud.collect(since_date=since_date)

    def collect_event_registry():
        return event_registry.collect(since_date=since_date)

    def collect_common_crawl():
        return common_crawl.collect(since_date=since_date)

    collectors = [
        google_news.collect,
        local_feeds.collect,
        collect_mediacloud,
        collect_event_registry,
        postal_web.collect,
        postal_history.collect,
        collect_common_crawl,
        gdelt.collect,
        official.collect,
        legifrance.collect,
        web_search.collect,
    ]
    if drill_queries:
        collectors.insert(1, lambda: google_news.collect(queries=drill_queries))
    recap = run_pipeline(
        conn,
        collectors,
        extractor_fn=ai["structured"],
        geocoder_fn=lambda commune, dept: geocode.geocode_commune_ou_lieu(
            commune, dept, cache=cache_geo),
        vigilance_fn=lambda art, raison: store.upsert_vigilance(
            conn, vigilance.depuis_article(art, raison)
        ) if vigilance.depuis_article(art, raison) else None,
        since_date=since_date,
        progress_fn=progress,
    )
    postal_reclassified = vigilance.reclassify_postal_vigilances(conn)
    progress("Ingestion des fermetures SG vérifiées", 55)
    # Fermetures SG nominativement vérifiées (localisateur officiel), géocodées
    # à l'adresse précise — Niveau 1, sans appel IA.
    geo_adr = lambda adr: geocode.geocode_adresse(adr, cache=cache_geo)
    sg_records = sg_locator.seed_closures() + sg_locator.crawled_closures(
        config.CACHE_DIR / "sg_crawl.json")
    n_sg = ingest_closures(conn, sg_records, geo_adr)
    progress("Chargement du référentiel agences", 65)
    branches = referentiel.fetch_osm_banques()
    lbp_branches = referentiel.fetch_lbp_agences()
    branches.extend(lbp_branches)
    for branche in branches:
        store.upsert_referentiel(conn, branche)
    total_referentiel = conn.execute("SELECT COUNT(*) FROM referentiel").fetchone()[0]
    progress("Signaux de vigilance Légifrance", 75)
    n_vigilances_legifrance = vigilance.ingest_articles(
        conn,
        legifrance.collect(),
        raison="signal faible Légifrance sans agence nominative validée",
    )

    # Éclatement des articles "plan multi-agences" en fermetures individuelles.
    n_plan = 0
    if config.PLAN_EXPLOSION_ENABLED:
        progress("Éclatement des plans multi-agences", 78)
        for art in plan_articles:
            try:
                closures = drilldown.fermetures_depuis_plan(
                    art, lambda c: geocode.geocode_commune(c, cache=cache_geo),
                    fetch_fn=fetch_text)
            except Exception as exc:
                print(f"[plan] éclatement en erreur: {exc}")
                continue
            for closure in closures:
                plan_geo = {
                    "lat": closure.get("lat"), "lon": closure.get("lon"),
                    "code_insee": closure.get("code_insee"),
                    "departement": closure.get("departement"),
                }
                decision = extraction_guard.evaluate(
                    closure, art, plan_geo, geocode_fn=geo_commune
                )
                if not decision.accepted:
                    print(f"[plan] fermeture rejetée: {decision.reason}")
                    continue
                store.upsert_closure(conn, closure)
                store.add_source(conn, closure["id"], {
                    "url": art.get("url"), "titre": art.get("titre"),
                    "source": art.get("source"), "date": art.get("date"),
                })
                n_plan += 1

    # Revue arborescente des vigilances qualifiées (score >= seuil) : chaque
    # signal devient le point de départ d'une recherche secondaire ciblée.
    review_recap = {"reviewed": 0, "closures_created": 0, "new_urls": 0}
    if config.VIGILANCE_REVIEW_ENABLED:
        progress("Revue arborescente des vigilances", 82)
        try:
            review_extractor = (
                ai["review"]
                if config.VIGILANCE_REVIEW_AI_ENABLED
                else None
            )
            review_recap = vigilance_review.reviser_vigilances(
                conn,
                search_fn=search_registry.search,
                extractor_fn=review_extractor,
                geocode_fn=geo_commune,
            )
        except Exception as exc:
            print(f"[vigilance_review] revue en erreur: {exc}")

    progress("Vérification des fermetures Banque Postale", 84)
    postal_enrichment = laposte_open_data.enrich_lbp_closures(conn)
    lbp_after = {
        row[0] for row in conn.execute(
            "SELECT id FROM closures WHERE banque='La Banque Postale'"
        )
    }
    lbp_window_total = conn.execute(
        """SELECT COUNT(*) FROM closures
           WHERE banque='La Banque Postale'
             AND (statut_temporel='a_venir' OR ? IS NULL OR date_fermeture>=?)""",
        (since_date, since_date),
    ).fetchone()[0]
    lbp_summary = {
        "new_this_run": len(lbp_after - lbp_before),
        "total_in_window": lbp_window_total,
        "total_all": len(lbp_after),
    }

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
    print("Fournisseur IA d'extraction:", ai["provider"])
    print("Récapitulatif presse:", recap)
    print("Synchronisation officielle La Poste:", postal_sync)
    print("Anciens articles postaux remis en file:", postal_requeued)
    print("Backlog postal traité sans IA:", postal_backfill)
    print("Vigilances postales reclassées:", postal_reclassified)
    print("Fermetures LBP enrichies:", postal_enrichment)
    print("Anciens marqueurs LBP mis en quarantaine:", lbp_quarantine)
    print("Bilan fermetures LBP:", lbp_summary)
    print("Fermetures SG vérifiées ingérées:", n_sg)
    print("Agences du référentiel OSM/LBP récupérées ce run:", len(branches))
    print("Agences La Banque Postale récupérées ce run:", len(lbp_branches))
    print("Agences du référentiel disponibles dans l'app:", total_referentiel)
    print("Signaux de vigilance Légifrance:", n_vigilances_legifrance)
    print("Fermetures issues de l'éclatement des plans:", n_plan)
    print("Revue des vigilances:", review_recap)
    print("Contrôles SIRENE effectués:", controles)
    print("Alertes audit extraction:", len(audit_findings))
    print("Export écrit dans", config.DATA_JSON)
    print("Tableau fermetures nettoyées:", config.EXPORT_DIR / "fermetures_nettoyees.csv")
    return {
        "window": window,
        "ai_provider": ai["provider"],
        "recap": recap,
        "postal_sync": postal_sync,
        "postal_requeued": postal_requeued,
        "postal_backfill": postal_backfill,
        "postal_reclassified": postal_reclassified,
        "postal_enrichment": postal_enrichment,
        "lbp_quarantine": lbp_quarantine,
        "lbp_summary": lbp_summary,
        "sg": n_sg,
        "referentiel": len(branches),
        "referentiel_lbp": len(lbp_branches),
        "referentiel_total": total_referentiel,
        "vigilances_legifrance": n_vigilances_legifrance,
        "plan_explosion": n_plan,
        "vigilance_review": review_recap,
        "controles": controles,
        "audit_findings": len(audit_findings),
        "export": str(config.DATA_JSON),
    }


def seed_main(path: str, *, reference: str | None = None):
    """Mode « seed URLs » : ingère une liste d'URLs curées puis exporte.

    `--seed-urls` accepte .txt/.csv/.xlsx ; `--seed-excel` réutilise le même
    Excel comme source d'URLs ET comme référence de comparaison.
    """
    conn = store.init_db(config.DB_PATH)
    ai = _build_ai_extractors()
    cache_geo: dict = {}

    progress("Chargement des URLs seed", 10)
    articles = seed.load_articles(path)
    progress(f"Ingestion seed ({len(articles)} URLs)", 30)
    recap = seed.ingest(
        conn, articles,
        extractor_fn=ai["structured"],
        geocode_fn=lambda c, d=None: geocode.geocode_commune_ou_lieu(c, d, cache=cache_geo),
        fetch_fn=fetch_text,
    )
    progress("Export des fichiers front", 90)
    geojson.ensure_departements_geojson()
    export.export_json(conn, config.DATA_JSON)
    export.export_fermetures_csv(conn, config.EXPORT_DIR / "fermetures_nettoyees.csv")
    progress("Terminé", 100)
    print("Seed URLs ingérées:", recap)
    print("Export écrit dans", config.DATA_JSON)

    if reference:
        try:
            from tools import compare_expected_closures as cmp
            rows = cmp.load_expected(reference)
            payload = cmp.load_payload(config.DATA_JSON)
            summary = cmp.summarize(cmp.compare(rows, payload))
            print("Comparaison référence:", summary)
            recap["comparaison"] = summary
        except Exception as exc:
            print(f"[seed] comparaison impossible: {exc}")
    return recap


def parse_args():
    parser = argparse.ArgumentParser(description="Lance la veille presse fermetures d'agences bancaires.")
    parser.add_argument("--since", help="Date de départ exacte au format YYYY-MM-DD.")
    parser.add_argument("--lookback-days", type=int, help="Nombre de jours à remonter depuis aujourd'hui.")
    parser.add_argument("--lookback-months", type=int, help="Nombre de mois approximatif à remonter depuis aujourd'hui.")
    parser.add_argument("--seed-urls", help="Ingère une liste d'URLs curées (.txt/.csv/.xlsx) puis exporte.")
    parser.add_argument("--seed-excel", help="Ingère les URLs de l'Excel de référence et compare le résultat.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.seed_excel:
        seed_main(args.seed_excel, reference=args.seed_excel)
    elif args.seed_urls:
        seed_main(args.seed_urls)
    else:
        main(_since_from_args(args))
