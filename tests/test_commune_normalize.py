from backend import commune_normalize as cn
from backend.dedup import closure_id
from backend.geocode import parse_ban


def _closure(commune, adresse=None):
    return {
        "id": closure_id("Société Générale", commune, "fermeture", adresse or ""),
        "banque": "Société Générale", "commune": commune,
        "code_insee": None, "departement": None, "type": "fermeture",
        "date_fermeture": "2026-01-15", "statut": "confirmé",
    }


def test_parse_ban_renvoie_la_commune_administrative():
    payload = {"features": [{
        "geometry": {"coordinates": [2.13, 47.99]},
        "properties": {"name": "Coëtquidan", "city": "Guer",
                       "citycode": "56075", "postcode": "56380"},
    }]}
    geo = parse_ban(payload)
    assert geo["commune"] == "Guer"
    assert geo["code_insee"] == "56075"


def test_normalise_localisation_vers_commune_administrative():
    geo = {"lat": 47.9, "lon": -2.1, "code_insee": "56075",
           "departement": "56", "commune": "Guer"}
    closure = cn.appliquer(_closure("Coëtquidan"), geo)
    assert closure["commune"] == "Guer"
    assert closure["agence_localisation"] == "Coëtquidan"
    assert closure["commune_originale"] == "Coëtquidan"


def test_normalise_recalcule_id_avec_localisation():
    geo = {"code_insee": "56075", "departement": "56", "commune": "Guer"}
    avant = _closure("Coëtquidan")["id"]
    closure = cn.appliquer(_closure("Coëtquidan"), geo)
    assert closure["id"] != avant
    # déterministe : commune administrative + localisation
    assert closure["id"] == closure_id("Société Générale", "Guer", "fermeture", "Coëtquidan")


def test_normalise_sans_difference_ne_touche_pas_la_commune():
    geo = {"code_insee": "56075", "departement": "56", "commune": "Guer"}
    closure = cn.appliquer(_closure("Guer"), geo)
    assert closure["commune"] == "Guer"
    assert closure.get("agence_localisation") in (None, "")


def test_normalise_sans_geo_inchange():
    base = _closure("Coëtquidan")
    closure = cn.appliquer(dict(base), None)
    assert closure["commune"] == "Coëtquidan"
    assert closure["id"] == base["id"]


def test_pas_de_fusion_si_adresses_differentes():
    # Deux agences dans la même commune mais à des adresses différentes
    # doivent garder des identifiants distincts.
    a = closure_id("BNP Paribas", "Paris", "fermeture", "12 rue de Rivoli")
    b = closure_id("BNP Paribas", "Paris", "fermeture", "300 avenue Daumesnil")
    assert a != b
