import json
from pathlib import Path

from backend import controle

FIXTURES = Path(__file__).parent / "fixtures"


def _fetch_fixture(nom):
    def fetch(url, **kwargs):
        assert "recherche-entreprises.api.gouv.fr/search" in url
        assert kwargs["params"]["q"]
        return json.loads((FIXTURES / nom).read_text(encoding="utf-8"))
    return fetch


def test_confirmer_fermeture_actif():
    statut = controle.confirmer_fermeture(
        "BNP Paribas", "Lyon", fetch=_fetch_fixture("sirene_actif.json")
    )
    assert statut == {
        "etat_administratif": "A",
        "siret": "12345678900010",
        "source": "SIRENE",
    }


def test_confirmer_fermeture_ferme():
    statut = controle.confirmer_fermeture(
        "BNP Paribas", "Lyon", fetch=_fetch_fixture("sirene_ferme.json")
    )
    assert statut["etat_administratif"] == "F"
    assert statut["siret"] == "12345678900028"


def test_confirmer_fermeture_introuvable():
    statut = controle.confirmer_fermeture(
        "Banque inconnue", "Nulle part", fetch=_fetch_fixture("sirene_vide.json")
    )
    assert statut == {"etat_administratif": None, "siret": None, "source": "SIRENE"}
