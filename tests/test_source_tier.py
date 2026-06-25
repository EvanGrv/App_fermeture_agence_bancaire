"""Tests for backend.source_tier — TDD RED first."""
import pytest
from backend.source_tier import tier


def test_tier_banque_officielle():
    """Tier A: official bank and government domains."""
    assert tier("https://www.credit-agricole.fr/actualites/fermeture-agence") == "A"
    assert tier("https://www.prefet69.gouv.fr/articles/annonce") == "A"


def test_tier_pqr():
    """Tier B: daily regional press (PQR)."""
    assert tier("https://www.ouest-france.fr/bretagne/fermeture") == "B"


def test_tier_complementaire():
    """Tier C: good complementary sources."""
    assert tier("https://www.francebleu.fr/infos/economie/fermeture") == "C"
    assert tier("https://actu.fr/normandie/fermeture-agence") == "C"


def test_tier_reseaux_sociaux():
    """Tier E: social networks and directories."""
    assert tier("https://www.facebook.com/pages/banque/123") == "E"


def test_tier_defaut():
    """Tier D: unknown press domain and empty string."""
    assert tier("https://www.unjournalinconnu.fr/article/fermeture") == "D"
    assert tier("") == "D"


def test_tier_sous_domaine():
    """Tier B: subdomain of a PQR domain."""
    assert tier("https://rennes.ouest-france.fr/news/fermeture") == "B"


# ── Fix A ──────────────────────────────────────────────────────────────────────
def test_tier_caisse_des_depots():
    """Tier A: caissedesdepots.fr must match (casing bug fix)."""
    assert tier("https://www.caissedesdepots.fr/actu") == "A"


# ── Fix B ──────────────────────────────────────────────────────────────────────
def test_news_google_avec_maps_en_query_reste_D():
    """news.google.com with 'maps' only in query string must stay D (aggregator)."""
    assert tier("https://news.google.com/search?q=maps") == "D"


def test_google_maps_est_E():
    """A genuine Google Maps link must be E."""
    assert tier("https://maps.google.com/maps?cid=123") == "E"


# ── Fix C ──────────────────────────────────────────────────────────────────────
def test_tier_france3_direct():
    """Tier C: france3.fr top-level domain must match."""
    assert tier("https://france3.fr/info/article") == "C"
