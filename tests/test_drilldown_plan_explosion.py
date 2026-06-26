from backend import drilldown


_COMMUNES_VALIDES = {
    "lons-le-saunier": "39300", "dole": "39198", "pontarlier": "25462",
    "champagnole": "39097", "morteau": "25411", "saint-claude": "39478",
    "arbois": "39013", "poligny": "39434", "salins-les-bains": "39500",
    "ornans": "25434",
}


def _geocode(commune, departement=None):
    cle = drilldown._normalise(commune).strip()
    insee = _COMMUNES_VALIDES.get(cle)
    if not insee:
        return None
    return {"lat": 46.0, "lon": 6.0, "code_insee": insee, "departement": insee[:2]}


def _article_plan():
    return {
        "titre": "Le Crédit Agricole de Franche-Comté ferme 10 agences",
        "texte": (
            "Le Crédit Agricole de Franche-Comté ferme 10 agences au 1er septembre 2026. "
            "Sont concernées les agences de Lons-le-Saunier, Dole, Pontarlier, "
            "Champagnole, Morteau, Saint-Claude, Arbois, Poligny, Salins-les-Bains "
            "et Ornans."
        ),
        "url": "https://ici.fr/franche-comte/credit-agricole-10-agences",
        "date": "2026-06-01",
        "source": "ici.fr",
    }


def test_date_commune_parsee():
    assert drilldown.date_commune_du_plan(
        "fermeture au 1er septembre 2026") == "2026-09-01"
    assert drilldown.date_commune_du_plan(
        "à compter du 30 juin 2026") == "2026-06-30"
    assert drilldown.date_commune_du_plan("aucune date ici") is None


def test_explosion_plan_genere_une_fermeture_par_commune():
    closures = drilldown.fermetures_depuis_plan(_article_plan(), _geocode)
    communes = {c["commune"] for c in closures}
    assert len(closures) == 10
    assert "Lons-le-Saunier" in communes
    assert "Ornans" in communes


def test_communes_candidates_accepte_connecteurs_francais():
    texte = (
        "Sont concernées les agences de Pays de Clerval, "
        "Pays de Montbenoît et Saint-Julien-sur-Suran."
    )
    assert drilldown.communes_candidates(texte) == [
        "Pays de Clerval", "Pays de Montbenoît", "Saint-Julien-sur-Suran"]


def test_explosion_plan_applique_la_date_commune():
    closures = drilldown.fermetures_depuis_plan(_article_plan(), _geocode)
    assert all(c["date_fermeture"] == "2026-09-01" for c in closures)


def test_explosion_plan_normalise_la_banque():
    closures = drilldown.fermetures_depuis_plan(_article_plan(), _geocode)
    assert all(c["banque"] == "Crédit Agricole" for c in closures)


def test_explosion_plan_rejette_communes_invalides():
    art = _article_plan()
    art["texte"] = art["texte"].replace("et Ornans.", "et Zzztopville.")
    closures = drilldown.fermetures_depuis_plan(art, _geocode)
    communes = {c["commune"] for c in closures}
    assert "Zzztopville" not in communes
    assert len(closures) == 9


def test_explosion_plan_cap_configurable():
    closures = drilldown.fermetures_depuis_plan(_article_plan(), _geocode, max_communes=3)
    assert len(closures) == 3


def test_explosion_plan_enrichit_geo_et_insee():
    closures = drilldown.fermetures_depuis_plan(_article_plan(), _geocode)
    lons = next(c for c in closures if c["commune"] == "Lons-le-Saunier")
    assert lons["code_insee"] == "39300"
    assert lons["type"] == "fermeture"
    assert lons["lat"] == 46.0


def test_explosion_ignore_article_non_plan():
    art = {"titre": "Une agence ferme à Lons-le-Saunier", "texte": "Rien de plus.",
           "url": "u", "date": "2026-01-01"}
    assert drilldown.fermetures_depuis_plan(art, _geocode) == []
