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


def test_load_xlsx_copilot_header_positionnel_banque(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    p = tmp_path / "copilot.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["²", "Agence / localisation", "Adresse", "Commune", "Département",
               "Région", "Latitude", "Longitude", "Date de fermeture",
               "Précision date", "Source principale", "Lien source"])
    ws.append(["Caisse d'Épargne", "Bannalec", "", "Bannalec", "Finistère",
               "", "", "", "2026-12-31", "", "MoneyVox",
               "https://moneyvox.fr/liste"])
    wb.save(p)

    arts = seed.load_articles(p)
    assert len(arts) == 1
    assert arts[0]["source"] == "MoneyVox"
    assert arts[0]["seed_targets"][0]["banque"] == "Caisse d'Épargne"


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


def test_ingest_seed_plan_conserve_commune_non_geocodee(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    article = {"titre": "La Caisse d'Épargne ferme plusieurs agences",
               "texte": "", "url": "https://moneyvox.fr/liste", "date": "2026-06-01",
               "source": "MoneyVox", "departement": None,
               "seed_targets": [
                   {"banque": "Caisse d'Épargne", "commune": "Bannalec",
                    "departement": "29", "date_fermeture": "2026-12-31"},
                   {"banque": "Caisse d'Épargne", "commune": "Commune Introuvable",
                    "departement": "45", "date_fermeture": "2026-12-31"},
               ]}

    def geocode_fn(commune, departement=None):
        if commune == "Bannalec":
            return {"lat": 47.9, "lon": -3.7, "code_insee": "29004",
                    "departement": "29", "commune": commune}
        return None

    recap = seed.ingest(conn, [article], extractor_fn=lambda _art: None,
                        geocode_fn=geocode_fn, fetch_fn=lambda _url: "")
    assert recap["fermetures"] == 1
    assert recap["rejets"] == 1
    assert conn.execute("SELECT COUNT(*) FROM closures").fetchone()[0] == 1
    row = conn.execute(
        "SELECT banque, commune, departement, url FROM closures_unlocated"
    ).fetchone()
    assert row == ("Caisse d'Épargne", "Commune Introuvable", "45",
                   "https://moneyvox.fr/liste")


def test_ingest_seed_resultat_structure_article_liste(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    article = {"titre": "La Caisse d'Épargne liste ses agences fermées",
               "texte": "Bannalec et Plonéour-Lanvern sont citées.",
               "url": "https://moneyvox.fr/liste", "date": "2026-06-01",
               "source": "MoneyVox", "departement": None}

    def extractor_fn(_art):
        return {
            "article_type": "list_closures",
            "closures": [
                {"bank": "Caisse d'Épargne", "commune": "Bannalec",
                 "departement": "29", "closure_type": "closure",
                 "status": "confirmed", "confidence": 0.8,
                 "evidence": "Bannalec est citée"},
                {"bank": "Caisse d'Épargne", "commune": "Plonéour-Lanvern",
                 "departement": "29", "closure_type": "closure",
                 "status": "confirmed", "confidence": 0.8,
                 "evidence": "Plonéour-Lanvern est citée"},
            ],
            "department_signals": [],
            "vague_signals": [],
            "confidence": 0.8,
            "needs_sonnet": False,
        }

    def geocode_fn(commune, departement=None):
        return {"lat": 47.9, "lon": -3.7, "code_insee": f"29{len(commune):03d}",
                "departement": "29", "commune": commune}

    recap = seed.ingest(conn, [article], extractor_fn=extractor_fn,
                        geocode_fn=geocode_fn, fetch_fn=None)
    assert recap["extraits"] == 1
    assert recap["fermetures"] == 2
    communes = {r[0] for r in conn.execute("SELECT commune FROM closures")}
    assert communes == {"Bannalec", "Plonéour-Lanvern"}


def test_ingest_seed_structure_sans_closure_retombe_sur_target_unique(tmp_path):
    conn = store.init_db(tmp_path / "t.db")
    article = {"titre": "Crédit Agricole Reuilly fermeture agence",
               "texte": "", "url": "https://ici.fr/reuilly", "date": "2026-06-01",
               "source": "ICI", "departement": "36",
               "seed_targets": [{
                   "banque": "Crédit Agricole Centre Ouest",
                   "commune": "Reuilly",
                   "departement": "36",
                   "date_fermeture": "2026-02-01",
               }]}

    def extractor_fn(_art):
        return {
            "article_type": "department_signal",
            "closures": [],
            "department_signals": [{
                "bank": "Crédit Agricole Centre Ouest",
                "departement": "36",
                "count": 1,
                "communes_mentioned": ["Reuilly"],
                "confidence": 0.7,
                "evidence": "Reuilly est mentionnée",
            }],
            "vague_signals": [],
            "confidence": 0.7,
            "needs_sonnet": False,
        }

    def geocode_fn(commune, departement=None):
        return {"lat": 47.0, "lon": 2.0, "code_insee": "36173",
                "departement": "36", "commune": commune}

    recap = seed.ingest(conn, [article], extractor_fn=extractor_fn,
                        geocode_fn=geocode_fn, fetch_fn=None)
    assert recap["fermetures"] == 1
    row = conn.execute("SELECT banque, commune FROM closures").fetchone()
    assert row == ("Crédit Agricole", "Reuilly")


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
