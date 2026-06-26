import pytest

import backend.store as store
from backend import seed


# --- Chargement des articles ------------------------------------------------

def test_load_txt_extrait_les_urls(tmp_path):
    p = tmp_path / "urls.txt"
    p.write_text(
        "https://ouest-france.fr/guer/bnp\n"
        "# commentaire sans url\n"
        "voir https://dna.fr/colmar-credit-agricole .\n",
        encoding="utf-8",
    )
    arts = seed.load_articles(p)
    urls = [a["url"] for a in arts]
    assert urls == [
        "https://ouest-france.fr/guer/bnp",
        "https://dna.fr/colmar-credit-agricole",
    ]
    assert all(a["source"] == "Seed URL" for a in arts)


def test_load_csv_avec_colonnes(tmp_path):
    p = tmp_path / "ref.csv"
    p.write_text(
        "Banque,Commune,Date de fermeture,Lien source\n"
        "BNP Paribas,Guer,2026-06-27,https://ouest-france.fr/guer/bnp\n",
        encoding="utf-8",
    )
    arts = seed.load_articles(p)
    assert len(arts) == 1
    a = arts[0]
    assert a["url"] == "https://ouest-france.fr/guer/bnp"
    assert a["date"] == "2026-06-27"
    assert "BNP Paribas" in a["titre"]


def test_load_xlsx_colonne_lien_source(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    p = tmp_path / "ref.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Banque", "Agence / localisation", "Commune", "Date de fermeture",
               "Lien source", "Éléments retenus"])
    ws.append(["BNP Paribas", "Coëtquidan", "Guer", "2026-06-27",
               "https://ouest-france.fr/guer/bnp", "L'agence ferme fin juin"])
    ws.append(["", "", "", "", "", ""])  # ligne vide ignorée
    wb.save(p)

    arts = seed.load_articles(p)
    assert len(arts) == 1
    assert arts[0]["url"] == "https://ouest-france.fr/guer/bnp"
    assert "Coëtquidan" in arts[0]["titre"]
    assert arts[0]["commune_attendue"] == "Guer"
    assert arts[0]["agence_localisation"] == "Coëtquidan"


def test_load_deduplique_les_urls(tmp_path):
    p = tmp_path / "urls.txt"
    p.write_text("https://x.fr/a\nhttps://x.fr/a\n", encoding="utf-8")
    assert len(seed.load_articles(p)) == 1


def test_load_xlsx_fusionne_les_lignes_partageant_un_article_plan(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    p = tmp_path / "ref.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Banque", "Agence / localisation", "Commune", "Lien source",
               "Éléments retenus"])
    ws.append(["Crédit Agricole de Franche-Comté", "Beaucourt", "Beaucourt",
               "https://ici.fr/fc", "Le Crédit Agricole va fermer dix agences."])
    ws.append(["Crédit Agricole de Franche-Comté", "Mandeure", "Mandeure",
               "https://ici.fr/fc", "Même article-plan."])
    wb.save(p)

    arts = seed.load_articles(p)
    assert len(arts) == 1
    assert arts[0]["seed_communes"] == ["Beaucourt", "Mandeure"]
    assert "Sont concernées les agences de Beaucourt et Mandeure" in arts[0]["texte"]


# --- Ingestion (sans réseau) ------------------------------------------------

def _geocode_guer(commune, departement=None):
    if commune in ("Guer", "Coëtquidan"):
        return {"lat": 47.9, "lon": -2.1, "code_insee": "56075",
                "departement": "56", "commune": "Guer"}
    return None


def test_ingest_cree_une_fermeture_et_rattache_commune(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    article = {"titre": "BNP Paribas Coëtquidan fermeture agence", "texte": "",
               "url": "https://ouest-france.fr/guer/bnp", "date": "2026-06-01",
               "source": "Ouest-France", "departement": "56"}

    def fetch_fn(url):
        return "L'agence BNP Paribas de Coëtquidan ferme le 27 juin 2026. " * 20

    def extractor_fn(art):
        # L'IA renvoie la localisation citée (Coëtquidan), pas la commune admin.
        return {"id": "seed1", "banque": "BNP Paribas", "commune": "Coëtquidan",
                "code_insee": None, "departement": "56", "type": "fermeture",
                "date_annonce": "2026-06-01", "date_fermeture": "2026-06-27",
                "statut": "confirmé", "fiabilite": 4, "lat": None, "lon": None,
                "citation": "ferme"}

    recap = seed.ingest(conn, [article], extractor_fn=extractor_fn,
                        geocode_fn=_geocode_guer, fetch_fn=fetch_fn)
    assert recap == {"urls": 1, "extraits": 1, "fermetures": 1,
                     "rejets": 0, "vigilances": 0}
    row = conn.execute(
        "SELECT banque, commune, agence_localisation FROM closures").fetchone()
    assert row[0] == "BNP Paribas"
    assert row[1] == "Guer"             # commune administrative (BAN)
    assert row[2] == "Coëtquidan"       # localisation d'agence conservée


def test_ingest_excel_utilise_commune_attendue_pour_eviter_mauvais_lieu(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    article = {"titre": "BNP Paribas Guer-Coëtquidan fermeture agence", "texte": "",
               "url": "https://ouest-france.fr/guer/bnp", "date": "2026-06-01",
               "source": "Ouest-France", "departement": "56",
               "commune_attendue": "Guer", "agence_localisation": "Coëtquidan"}

    def extractor_fn(_art):
        return {"id": "seed1", "banque": "BNP Paribas", "commune": "Guer-Coëtquidan",
                "code_insee": None, "departement": "56", "type": "fermeture",
                "date_annonce": "2026-06-01", "date_fermeture": "2026-06-27",
                "statut": "confirmé", "fiabilite": 4, "lat": None, "lon": None,
                "citation": "ferme"}

    recap = seed.ingest(conn, [article], extractor_fn=extractor_fn,
                        geocode_fn=_geocode_guer, fetch_fn=lambda _url: "")
    assert recap["fermetures"] == 1
    row = conn.execute(
        "SELECT commune, agence_localisation, commune_originale FROM closures").fetchone()
    assert row == ("Guer", "Coëtquidan", "Guer-Coëtquidan")


def test_ingest_seed_plan_eclate_plusieurs_communes(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    article = {"titre": "Le Crédit Agricole de Franche-Comté ferme 10 agences",
               "texte": "", "url": "https://ici.fr/fc", "date": "2026-06-01",
               "source": "ICI", "departement": None,
               "seed_targets": [
                   {"banque": "Crédit Agricole de Franche-Comté",
                    "commune": "Beaucourt", "departement": "90",
                    "date_fermeture": "2026-09-01"},
                   {"banque": "Crédit Agricole de Franche-Comté",
                    "commune": "Mandeure", "departement": "25",
                    "date_fermeture": "2026-09-01"},
                   {"banque": "Crédit Agricole de Franche-Comté",
                    "commune": "Vauvillers", "departement": "70",
                    "date_fermeture": "2026-09-01"},
               ]}

    def fetch_fn(_url):
        return (
            "Le Crédit Agricole de Franche-Comté ferme 10 agences au "
            "1er septembre 2026. Sont concernées les agences de Beaucourt, "
            "Mandeure et Vauvillers."
        )

    def geocode_fn(commune, departement=None):
        codes = {"Beaucourt": "90009", "Mandeure": "25367", "Vauvillers": "70526"}
        code = codes.get(commune)
        if not code:
            return None
        return {"lat": 47.0, "lon": 6.0, "code_insee": code,
                "departement": code[:2], "commune": commune}

    recap = seed.ingest(conn, [article], extractor_fn=lambda _art: None,
                        geocode_fn=geocode_fn, fetch_fn=fetch_fn)
    assert recap["fermetures"] == 3
    communes = {r[0] for r in conn.execute("SELECT commune FROM closures")}
    assert communes == {"Beaucourt", "Mandeure", "Vauvillers"}


def test_ingest_extraction_vide_compte_vigilance(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    article = {"titre": "t", "texte": "x" * 500, "url": "https://x.fr/a",
               "date": None, "source": "s"}
    recap = seed.ingest(conn, [article], extractor_fn=lambda a: None,
                        geocode_fn=_geocode_guer, fetch_fn=None)
    assert recap["fermetures"] == 0
    assert recap["vigilances"] == 1


def test_ingest_fetch_en_erreur_ne_casse_pas(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    article = {"titre": "t", "texte": "", "url": "https://x.fr/a", "date": None,
               "source": "s"}

    def fetch_boom(url):
        raise RuntimeError("réseau HS")

    recap = seed.ingest(conn, [article], extractor_fn=lambda a: None,
                        geocode_fn=_geocode_guer, fetch_fn=fetch_boom)
    assert recap["urls"] == 1  # pas d'exception propagée
