import json

import pytest

from tools import compare_expected_closures as cmp


# --- Fixtures ---------------------------------------------------------------

def _payload() -> dict:
    """Payload data.json minimal couvrant tous les cas de classification."""
    return {
        "closures": [
            # présent et complet
            {"banque": "Crédit Agricole", "commune": "Reuilly",
             "code_insee": "36173", "date_fermeture": "2026-02-01", "citation": "", "sources": []},
            # présent mais sans date
            {"banque": "Crédit Mutuel", "commune": "Brest",
             "code_insee": "29019", "date_fermeture": "", "citation": "", "sources": []},
            # capté sous la localisation d'agence (Coëtquidan) au lieu de la commune (Guer)
            {"banque": "Société Générale", "commune": "Coëtquidan",
             "code_insee": "56075", "date_fermeture": "2026-01-15", "citation": "", "sources": []},
            # présent mais malformé : pas de code INSEE
            {"banque": "LCL", "commune": "Vimoutiers",
             "code_insee": None, "date_fermeture": "2026-03-01", "citation": "", "sources": []},
        ],
        "vigilances": [
            {"banque": "BNP Paribas", "titre": "La BNP Paribas de Bar-le-Duc menacée",
             "extrait": "Les clients s'inquiètent.", "score": 3},
            {"banque": "Crédit Agricole",
             "titre": "Crédit Agricole Franche-Comté ferme 10 agences",
             "extrait": "Dont Lons-le-Saunier, Dole et Pontarlier.", "score": 4},
        ],
    }


# --- load_expected ----------------------------------------------------------

def test_load_expected_csv(tmp_path):
    csv_path = tmp_path / "ref.csv"
    csv_path.write_text(
        "banque,commune,date_fermeture,agence_localisation,plan\n"
        "BNP Paribas,Bar-le-Duc,2026-03-31,,0\n"
        "Société Générale,Guer,,Coëtquidan,0\n"
        "Crédit Agricole,Lons-le-Saunier,2026-09-01,,1\n",
        encoding="utf-8",
    )
    rows = cmp.load_expected(csv_path)
    assert len(rows) == 3
    assert rows[0]["banque"] == "BNP Paribas"
    assert rows[0]["commune"] == "Bar-le-Duc"
    assert rows[1]["agence_localisation"] == "Coëtquidan"
    assert rows[2]["plan"] is True
    assert rows[0]["plan"] is False


def test_load_expected_xlsx_entetes_francais(tmp_path):
    """L'Excel de référence (en-têtes FR, dates texte) est chargé sans planter."""
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "ref.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([
        "Banque", "Agence / localisation", "Commune", "Département", "Région",
        "Date de fermeture", "Précision de date", "Source", "Lien source",
        "Éléments retenus", "Score de confiance",
    ])
    ws.append([
        "Caisse d'Épargne", "Pont-de-Briques – rue du Docteur-Brousse",
        "Saint-Étienne-au-Mont", "Pas-de-Calais", "Hauts-de-France",
        "Semaine précédant le 23/06/2026", "Date relative", "EuropeSays",
        "https://europesays.com/fr/1020111/", "fermeture soudaine", 80,
    ])
    ws.append([
        "Crédit Agricole de Franche-Comté", "Beaucourt", "Beaucourt",
        "Territoire de Belfort", "Bourgogne-Franche-Comté", "2026-09-01",
        "Date commune publiée pour les 10 agences", "ICI",
        "https://ici.fr/x", "le Crédit Agricole va fermer dix agences", 90,
    ])
    wb.save(path)

    rows = cmp.load_expected(path)
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["banque"] == "Caisse d'Épargne"
    assert r0["commune"] == "Saint-Étienne-au-Mont"
    assert r0["agence_localisation"].startswith("Pont-de-Briques")
    # La date texte est conservée telle quelle, sans erreur de parsing.
    assert r0["date_fermeture"] == "Semaine précédant le 23/06/2026"
    # La ligne « dix agences » est reconnue comme plan sans colonne dédiée.
    assert rows[1]["plan"] is True


# --- classify ---------------------------------------------------------------

def test_classify_present_closure():
    row = {"banque": "Crédit Agricole", "commune": "Reuilly",
           "date_fermeture": "2026-02-01", "agence_localisation": "", "plan": False}
    assert cmp.classify(row, _payload()) == cmp.STATUS_PRESENT


def test_classify_missing_date():
    row = {"banque": "Crédit Mutuel", "commune": "Brest",
           "date_fermeture": "2026-05-01", "agence_localisation": "", "plan": False}
    assert cmp.classify(row, _payload()) == cmp.STATUS_MISSING_DATE


def test_classify_present_malformed_when_no_insee():
    row = {"banque": "LCL", "commune": "Vimoutiers",
           "date_fermeture": "2026-03-01", "agence_localisation": "", "plan": False}
    assert cmp.classify(row, _payload()) == cmp.STATUS_MALFORMED


def test_classify_bad_commune_normalization():
    row = {"banque": "Société Générale", "commune": "Guer",
           "date_fermeture": "", "agence_localisation": "Coëtquidan", "plan": False}
    assert cmp.classify(row, _payload()) == cmp.STATUS_BAD_COMMUNE


def test_classify_present_vigilance():
    row = {"banque": "BNP Paribas", "commune": "Bar-le-Duc",
           "date_fermeture": "2026-03-31", "agence_localisation": "", "plan": False}
    assert cmp.classify(row, _payload()) == cmp.STATUS_VIGILANCE


def test_classify_plan_not_exploded():
    row = {"banque": "Crédit Agricole", "commune": "Lons-le-Saunier",
           "date_fermeture": "2026-09-01", "agence_localisation": "", "plan": True}
    assert cmp.classify(row, _payload()) == cmp.STATUS_PLAN


def test_classify_plan_not_exploded_avec_banque_regionale_de():
    payload = {
        "closures": [],
        "vigilances": [{
            "banque": "Crédit Agricole",
            "titre": "Le Crédit Agricole va fermer dix agences bancaires en Franche-Comté",
            "extrait": "certaines mairies se mobilisent",
            "score": 3,
        }],
    }
    row = {"banque": "Crédit Agricole de Franche-Comté", "commune": "Beaucourt",
           "date_fermeture": "2026-09-01", "agence_localisation": "", "plan": True}
    assert cmp.classify(row, payload) == cmp.STATUS_PLAN


def test_classify_absent():
    row = {"banque": "LCL", "commune": "Nulleville",
           "date_fermeture": "", "agence_localisation": "", "plan": False}
    assert cmp.classify(row, _payload()) == cmp.STATUS_ABSENT


# --- compare + summarize ----------------------------------------------------

def test_compare_and_summarize():
    rows = [
        {"banque": "Crédit Agricole", "commune": "Reuilly",
         "date_fermeture": "2026-02-01", "agence_localisation": "", "plan": False},
        {"banque": "LCL", "commune": "Nulleville",
         "date_fermeture": "", "agence_localisation": "", "plan": False},
        {"banque": "BNP Paribas", "commune": "Bar-le-Duc",
         "date_fermeture": "", "agence_localisation": "", "plan": False},
    ]
    results = cmp.compare(rows, _payload())
    assert [r["status"] for r in results] == [
        cmp.STATUS_PRESENT, cmp.STATUS_ABSENT, cmp.STATUS_VIGILANCE]
    summary = cmp.summarize(results)
    assert summary[cmp.STATUS_PRESENT] == 1
    assert summary[cmp.STATUS_ABSENT] == 1
    assert summary[cmp.STATUS_VIGILANCE] == 1
