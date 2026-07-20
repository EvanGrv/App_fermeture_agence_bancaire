from backend import query_builder as qb


def test_build_queries_inclut_banque_et_commune():
    queries = qb.build_queries("BNP Paribas", "Bar-le-Duc", max_queries=50)
    assert queries  # non vide
    assert all("Bar-le-Duc" in q for q in queries)
    assert any("BNP Paribas" in q and "fermeture" in q.lower() for q in queries)


def test_build_queries_genere_des_requetes_site_par_domaine():
    queries = qb.build_queries(
        "Crédit Agricole", "Colmar",
        domains=["dna.fr", "estrepublicain.fr"], max_queries=50,
    )
    assert any(q.startswith("site:dna.fr") for q in queries)
    assert any(q.startswith("site:estrepublicain.fr") for q in queries)


def test_build_queries_inclut_les_formulations():
    queries = qb.build_queries("BNP Paribas", "Bar-le-Duc", max_queries=50)
    joined = " | ".join(queries)
    assert "fermera définitivement" in joined
    assert "cessera son activité" in joined


def test_build_queries_inclut_canal_postal_lbp():
    queries = qb.build_queries("La Banque Postale", "Bar-le-Duc", max_queries=50)
    joined = " | ".join(queries)
    assert "fermeture bureau de poste" in joined
    assert "services financiers Banque Postale" in joined


def test_build_queries_preserve_accents_et_variantes_banque():
    queries = qb.build_queries(
        "Crédit Agricole Franche-Comté", "Lons-le-Saunier", max_queries=50)
    joined = " | ".join(queries)
    # La variante régionale et les accents sont conservés tels quels.
    assert "Crédit Agricole Franche-Comté" in joined
    assert "Lons-le-Saunier" in joined


def test_build_queries_deduplique_et_respecte_la_limite():
    queries = qb.build_queries("BNP Paribas", "Bar-le-Duc", max_queries=5)
    assert len(queries) <= 5
    assert len(queries) == len(set(queries))


def test_build_queries_est_stable():
    a = qb.build_queries("BNP Paribas", "Bar-le-Duc", domains=["estrepublicain.fr"])
    b = qb.build_queries("BNP Paribas", "Bar-le-Duc", domains=["estrepublicain.fr"])
    assert a == b


def test_build_queries_sans_commune_ou_banque_retourne_vide():
    assert qb.build_queries("BNP Paribas", "") == []
    assert qb.build_queries("", "Bar-le-Duc") == []
