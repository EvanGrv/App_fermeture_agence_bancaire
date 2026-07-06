# tests/test_dedup.py
from backend.dedup import closure_id, normalise_cle

# Pre-computed stable value for regression testing (3-arg form, no adresse)
_STABLE_ID = "19e5a382218f8aca"

def test_id_stable_et_deterministe():
    a = closure_id("Société Générale", "Rennes", "fermeture")
    b = closure_id("Société Générale", "Rennes", "fermeture")
    assert a == b
    assert len(a) == 16

def test_id_insensible_casse_accents_espaces():
    a = closure_id("Société Générale", "Rennes", "fermeture")
    b = closure_id("societe generale ", " RENNES", "Fermeture")
    assert a == b

def test_id_distinct_si_type_differe():
    assert closure_id("BNP", "Lyon", "fermeture") != closure_id("BNP", "Lyon", "fusion")

def test_normalise_cle():
    assert normalise_cle("  Société  Générale ") == "societe generale"
    assert normalise_cle("Caisse d’Épargne") == "caisse d'epargne"
    assert normalise_cle("Caisse d'Épargne") == "caisse d'epargne"


# ---------------------------------------------------------------------------
# Task 16 — Part 2: optional adresse component in event key
# ---------------------------------------------------------------------------

def test_closure_id_stable_sans_adresse():
    """adresse omis ou vide → id identique à la forme 3-arg pré-existante."""
    assert closure_id("BNP Paribas", "Lyon", "fermeture") == _STABLE_ID
    assert closure_id("BNP Paribas", "Lyon", "fermeture", adresse="") == _STABLE_ID
    assert closure_id("BNP Paribas", "Lyon", "fermeture", adresse="   ") == _STABLE_ID


def test_closure_id_adresse_distingue():
    """Deux adresses différentes → deux ids distincts; adresse vide → id 3-arg."""
    id_sans = closure_id("BNP Paribas", "Paris", "fermeture")
    id_rue1 = closure_id("BNP Paribas", "Paris", "fermeture", adresse="12 rue de Rivoli")
    id_rue2 = closure_id("BNP Paribas", "Paris", "fermeture", adresse="5 avenue de l'Opéra")
    assert id_rue1 != id_rue2
    assert id_rue1 != id_sans
    assert id_rue2 != id_sans
    # empty adresse → same as no adresse
    assert closure_id("BNP Paribas", "Paris", "fermeture", adresse="") == id_sans
