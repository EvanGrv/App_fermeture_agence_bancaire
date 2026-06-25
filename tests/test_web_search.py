import pytest
from backend.collectors import web_search


def test_collect_sans_cle_retourne_vide(monkeypatch):
    """Sans clé API, collect retourne [] et affiche un message."""
    monkeypatch.delenv("WEB_SEARCH_API_KEY", raising=False)
    result = web_search.collect()
    assert result == []


def test_normalize_result_mappe_les_champs():
    """normalize_result mappe les champs génériques vers le schéma article."""
    raw = {
        "title": "Banque ferme agence en Bretagne",
        "snippet": "Une agence bancaire ferme ses portes au cœur du centre-ville.",
        "link": "https://example.com/article1",
        "date": "2025-01-15",
    }
    result = web_search.normalize_result(raw)
    assert result["titre"] == "Banque ferme agence en Bretagne"
    assert result["texte"] == "Une agence bancaire ferme ses portes au cœur du centre-ville."
    assert result["url"] == "https://example.com/article1"
    assert result["date"] == "2025-01-15"
    assert result["source"] == "Recherche web"
    assert result["departement"] is None
