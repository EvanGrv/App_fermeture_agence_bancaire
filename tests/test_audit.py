from datetime import date

from backend import audit


def test_audit_detecte_closure_non_publiable_et_citation_suspecte():
    data = {
        "closures": [{
            "id": "bad",
            "banque": "Crédit Agricole",
            "commune": "inconnu",
            "departement": None,
            "code_insee": None,
            "lat": None,
            "lon": None,
            "citation": "suppressions de postes et fermetures d'agences, appel à la grève",
            "sources": [{"titre": "Une grande première au Crédit Agricole", "url": "https://bfmtv.test"}],
        }]
    }

    findings = audit.audit_data(data)

    assert {item["type"] for item in findings} >= {"closure_non_publiable", "citation_suspecte"}
    assert any(item["severity"] == "error" for item in findings)


def test_audit_signale_communes_proches_distinctes():
    data = {
        "closures": [
            {
                "id": "a",
                "banque": "Crédit Agricole",
                "commune": "La Capelle",
                "departement": "02",
                "code_insee": "02141",
                "lat": 49.9,
                "lon": 3.9,
                "citation": "fermeture de l'agence",
                "sources": [],
            },
            {
                "id": "b",
                "banque": "Crédit Agricole",
                "commune": "La Capelle-lès-Boulogne",
                "departement": "62",
                "code_insee": "62908",
                "lat": 50.7,
                "lon": 1.7,
                "citation": "fermeture de l'agence",
                "sources": [],
            },
        ]
    }

    findings = audit.audit_data(data)

    assert not [item for item in findings if item["severity"] == "error"]
    assert any(item["type"] == "communes_proches" for item in findings)


def test_audit_signale_article_ancien_sans_date_fermeture():
    data = {
        "closures": [{
            "id": "old",
            "banque": "Crédit Agricole",
            "commune": "Écueillé",
            "departement": "36",
            "code_insee": "36069",
            "lat": 47.0,
            "lon": 1.3,
            "date_annonce": "2026-01-22",
            "date_fermeture": None,
            "citation": "l'agence du Crédit agricole d'Écueillé bientôt fermée",
            "sources": [],
        }]
    }

    findings = audit.audit_data(data, today=date(2026, 6, 24))

    assert any(item["type"] == "date_fermeture_absente" for item in findings)
