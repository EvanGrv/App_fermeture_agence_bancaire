"""Tests d'acceptation Phase 8 : les cas de référence manqués sont couverts par
le query builder, l'éclatement des plans et le comparateur de couverture.
"""
from pathlib import Path

from backend import query_builder, drilldown
from tools import compare_expected_closures as cmp

FIXTURE = Path(__file__).parent / "fixtures" / "expected_missing_closures.csv"

_PLAN_COMMUNES = {
    "lons-le-saunier": "39300", "dole": "39198", "pontarlier": "25462",
}


def _geocode_plan(commune, departement=None):
    insee = _PLAN_COMMUNES.get(drilldown._normalise(commune).strip())
    if not insee:
        return None
    return {"lat": 46.0, "lon": 6.0, "code_insee": insee, "departement": insee[:2]}


def test_fixture_chargeable_et_complete():
    rows = cmp.load_expected(FIXTURE)
    communes = {r["commune"] for r in rows}
    for attendu in ["Reuilly", "Bar-le-Duc", "Colmar", "Guer",
                    "Chalon-sur-Saône", "Les Grandes-Ventes",
                    "Pleudihen-sur-Rance", "Plouguenast-Langast"]:
        assert attendu in communes


def test_fixture_reflete_l_excel_cas_corriges():
    """La fixture doit reprendre exactement les banques/communes de l'Excel."""
    rows = cmp.load_expected(FIXTURE)
    par_commune = {r["commune"]: r for r in rows}
    # Cas explicitement corrigés (cf. tâche 11).
    assert par_commune["Saint-Cyr-sur-Loire"]["banque"] == "Crédit Mutuel"
    assert par_commune["Pleudihen-sur-Rance"]["banque"] == "Crédit Mutuel de Bretagne"
    assert par_commune["Guer"]["banque"] == "BNP Paribas"
    assert par_commune["Guer"]["agence_localisation"] == "Coëtquidan"
    # 10 agences du plan Franche-Comté.
    plan = [r for r in rows if r["plan"]]
    assert len(plan) == 10
    assert all(r["banque"] == "Crédit Agricole de Franche-Comté" for r in plan)
    assert {"Beaucourt", "Vauvillers", "Charquemont"} <= {r["commune"] for r in plan}
    assert len(rows) == 22


def test_query_builder_cible_chaque_cas():
    rows = cmp.load_expected(FIXTURE)
    for row in rows:
        queries = query_builder.build_queries(row["banque"], row["commune"])
        assert queries, f"aucune requête pour {row['commune']}"
        assert any(row["commune"] in q for q in queries)


def test_explosion_plan_produit_les_communes_franche_comte():
    article = {
        "titre": "Le Crédit Agricole de Franche-Comté ferme ses agences",
        "texte": (
            "Le Crédit Agricole de Franche-Comté ferme plusieurs agences au "
            "1er septembre 2026. Sont concernées les agences de Lons-le-Saunier, "
            "Dole et Pontarlier."
        ),
        "url": "https://ici.fr/fc", "date": "2026-06-01", "source": "ici.fr",
    }
    closures = drilldown.fermetures_depuis_plan(article, _geocode_plan)
    communes = {c["commune"] for c in closures}
    assert communes == {"Lons-le-Saunier", "Dole", "Pontarlier"}
    assert all(c["date_fermeture"] == "2026-09-01" for c in closures)


def test_comparateur_classe_present_absent_vigilance():
    payload = {
        "closures": [
            {"banque": "Crédit Agricole", "commune": "Reuilly",
             "code_insee": "36173", "date_fermeture": "2026-02-01"},
        ],
        "vigilances": [
            {"banque": "BNP Paribas", "titre": "BNP Paribas Bar-le-Duc",
             "extrait": "menace", "score": 3},
        ],
    }
    present = cmp.classify(
        {"banque": "Crédit Agricole", "commune": "Reuilly",
         "date_fermeture": "", "agence_localisation": "", "plan": False}, payload)
    vigilance = cmp.classify(
        {"banque": "BNP Paribas", "commune": "Bar-le-Duc",
         "date_fermeture": "", "agence_localisation": "", "plan": False}, payload)
    absent = cmp.classify(
        {"banque": "Crédit Agricole", "commune": "Les Grandes-Ventes",
         "date_fermeture": "", "agence_localisation": "", "plan": False}, payload)
    assert present == cmp.STATUS_PRESENT
    assert vigilance == cmp.STATUS_VIGILANCE
    assert absent == cmp.STATUS_ABSENT
