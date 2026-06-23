# tests/test_dedup.py
from backend.dedup import closure_id, normalise_cle

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
