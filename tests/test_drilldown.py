"""Tests TDD pour backend/drilldown.py — Task 13.

Ordre : RED d'abord (avant création du module), puis GREEN.
"""
import pytest
from backend import drilldown


# ---------------------------------------------------------------------------
# 1. est_plan
# ---------------------------------------------------------------------------

class TestEstPlan:
    def test_va_fermer_sept_agences(self):
        texte = "Le Crédit Agricole va fermer sept agences en Haute-Vienne."
        assert drilldown.est_plan(texte) is True

    def test_une_vingtaine_dagences(self):
        texte = "La banque prévoit la fermeture d'une vingtaine d'agences dans la région."
        assert drilldown.est_plan(texte) is True

    def test_plan_de_fermeture(self):
        texte = "Annonce d'un plan de fermeture massif dans le réseau bancaire."
        assert drilldown.est_plan(texte) is True

    def test_reorganisation_du_reseau(self):
        texte = "Réorganisation du réseau bancaire : plusieurs sites seront regroupés."
        assert drilldown.est_plan(texte) is True

    def test_reorganisation_territoriale(self):
        texte = "La banque engage une réorganisation territoriale de grande ampleur."
        assert drilldown.est_plan(texte) is True

    def test_plusieurs_agences(self):
        texte = "Le groupe va fermer plusieurs agences dans le département."
        assert drilldown.est_plan(texte) is True

    def test_deux_agences(self):
        texte = "La banque ferme deux agences en Corrèze."
        assert drilldown.est_plan(texte) is True

    def test_une_dizaine(self):
        texte = "Une dizaine d'agences seront supprimées d'ici fin 2025."
        assert drilldown.est_plan(texte) is True

    def test_une_seule_agence_n_est_pas_plan(self):
        # "1 agences" is grammatically odd but was previously matched by \d+;
        # single-quantity digit must not trigger plan detection.
        texte = "La banque ferme 1 agences de Tulle"
        assert drilldown.est_plan(texte) is False

    def test_false_single_closure(self):
        texte = "Le Crédit Agricole ferme son agence de Tulle."
        assert drilldown.est_plan(texte) is False

    def test_false_no_quantity(self):
        texte = "La banque rénove son agence principale à Limoges."
        assert drilldown.est_plan(texte) is False

    def test_case_insensitive(self):
        texte = "PLAN DE FERMETURE DES AGENCES."
        assert drilldown.est_plan(texte) is True

    def test_accent_insensitive_reorganisation(self):
        # sans accent
        texte = "reorganisation du reseau bancaire agences."
        assert drilldown.est_plan(texte) is True


# ---------------------------------------------------------------------------
# 2. communes_candidates
# ---------------------------------------------------------------------------

class TestCommunesCandidates:
    def test_agences_de_liste(self):
        texte = "les agences de Bessines, Ambazac et Nieul ferment"
        result = drilldown.communes_candidates(texte)
        assert result == ["Bessines", "Ambazac", "Nieul"]

    def test_a_liste(self):
        texte = "fermetures à Rochechouart, Saint-Junien et Bellac."
        result = drilldown.communes_candidates(texte)
        assert "Rochechouart" in result
        assert "Saint-Junien" in result
        assert "Bellac" in result

    def test_communes_de_liste(self):
        texte = "agences dans les communes de Nexon, Châlus et Oradour fermeront."
        result = drilldown.communes_candidates(texte)
        assert "Nexon" in result
        assert "Châlus" in result
        assert "Oradour" in result

    def test_drops_lowercase_tokens(self):
        texte = "agences de Bessines, ambazac et Nieul ferment"
        result = drilldown.communes_candidates(texte)
        # ambazac is all-lowercase → dropped
        assert "ambazac" not in result
        assert "Bessines" in result
        assert "Nieul" in result

    def test_drops_tokens_with_digits(self):
        texte = "agences de Bessines, 3ème et Nieul ferment"
        result = drilldown.communes_candidates(texte)
        assert "3ème" not in result
        assert "Bessines" in result

    def test_dedup_order_preserving(self):
        texte = "agences de Bessines, Ambazac, Bessines et Nieul ferment"
        result = drilldown.communes_candidates(texte)
        # Bessines appears twice but deduplicated
        assert result.count("Bessines") == 1
        assert result.index("Bessines") < result.index("Ambazac")

    def test_cap_at_20(self):
        noms = ", ".join(f"Ville{i:02d}" for i in range(30))
        texte = f"agences de {noms} ferment"
        result = drilldown.communes_candidates(texte)
        assert len(result) <= 20

    def test_no_cue_returns_empty_or_limited(self):
        texte = "La banque réduit ses effectifs globalement."
        result = drilldown.communes_candidates(texte)
        # Without any cue, nothing meaningful extracted
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 3. valider_communes
# ---------------------------------------------------------------------------

class TestValiderCommunes:
    def _make_geocode_fn(self, valid_communes):
        """Spy: returns {'code_insee': 'X'} for known communes, None otherwise."""
        def geocode_fn(candidate):
            if candidate in valid_communes:
                return {"code_insee": "X", "departement": "87"}
            return None
        return geocode_fn

    def test_keeps_valid_drops_invalid(self):
        candidates = ["Bessines", "Ambazac", "Nieul", "FakeTown"]
        geocode_fn = self._make_geocode_fn({"Bessines", "Ambazac", "Nieul"})
        result = drilldown.valider_communes(candidates, geocode_fn)
        assert result == ["Bessines", "Ambazac", "Nieul"]
        assert "FakeTown" not in result

    def test_cap_at_8(self):
        valid = {f"Commune{i}" for i in range(15)}
        candidates = list(valid)
        geocode_fn = self._make_geocode_fn(valid)
        result = drilldown.valider_communes(candidates, geocode_fn)
        assert len(result) <= 8

    def test_empty_result_dict_without_code_insee(self):
        """A result without code_insee should be excluded."""
        candidates = ["Bessines", "Ambazac"]
        def geocode_fn(c):
            if c == "Bessines":
                return {"lat": 1.0, "lon": 2.0}  # no code_insee
            return {"code_insee": "87X", "departement": "87"}
        result = drilldown.valider_communes(candidates, geocode_fn)
        assert "Bessines" not in result
        assert "Ambazac" in result

    def test_order_preserving(self):
        candidates = ["Nieul", "Ambazac", "Bessines"]
        geocode_fn = self._make_geocode_fn({"Nieul", "Ambazac", "Bessines"})
        result = drilldown.valider_communes(candidates, geocode_fn)
        assert result == ["Nieul", "Ambazac", "Bessines"]

    def test_dedup(self):
        candidates = ["Bessines", "Ambazac", "Bessines"]
        geocode_fn = self._make_geocode_fn({"Bessines", "Ambazac"})
        result = drilldown.valider_communes(candidates, geocode_fn)
        assert result.count("Bessines") == 1


# ---------------------------------------------------------------------------
# 4. _detecter_banque
# ---------------------------------------------------------------------------

class TestDetecterBanque:
    def test_credit_agricole(self):
        texte = "Le Crédit Agricole va fermer plusieurs agences."
        assert drilldown._detecter_banque(texte) == "Crédit Agricole"

    def test_bnp(self):
        texte = "BNP Paribas annonce la fermeture de ses agences."
        result = drilldown._detecter_banque(texte)
        assert result in ("BNP Paribas", "BNP")

    def test_regional_brand_maps_to_canonical(self):
        # "CA Centre-Est" should map to "Crédit Agricole"
        texte = "CA Centre-Est va fermer plusieurs agences en Bourgogne."
        result = drilldown._detecter_banque(texte)
        assert result == "Crédit Agricole"

    def test_caisse_epargne_regional(self):
        # "Caisse d'Épargne Auvergne Limousin" → canonical "Caisse d'Épargne"
        texte = "La Caisse d'Épargne Auvergne Limousin annonce un plan de fermeture."
        result = drilldown._detecter_banque(texte)
        assert result == "Caisse d'Épargne"

    def test_no_bank_returns_none(self):
        texte = "Le maire annonce la rénovation du centre-ville."
        result = drilldown._detecter_banque(texte)
        assert result is None

    def test_lcl(self):
        texte = "LCL ferme plusieurs agences dans le Limousin."
        result = drilldown._detecter_banque(texte)
        assert result == "LCL"


# ---------------------------------------------------------------------------
# 5. requetes_communes
# ---------------------------------------------------------------------------

class TestRequetesCommunes:
    def test_builds_queries(self):
        queries = drilldown.requetes_communes("Crédit Agricole", ["Bessines", "Ambazac"])
        assert queries == [
            "Crédit Agricole fermeture agence Bessines",
            "Crédit Agricole fermeture agence Ambazac",
        ]

    def test_empty_communes(self):
        assert drilldown.requetes_communes("BNP", []) == []


# ---------------------------------------------------------------------------
# 6. requetes_depuis_articles — end-to-end
# ---------------------------------------------------------------------------

class TestRequetesDepuisArticles:
    def _make_geocode_fn(self, valid_communes):
        def geocode_fn(candidate):
            if candidate in valid_communes:
                return {"code_insee": "87X", "departement": "87"}
            return None
        return geocode_fn

    def _plan_article(self, titre="", texte=""):
        return {"titre": titre, "texte": texte}

    def test_end_to_end(self):
        article = self._plan_article(
            titre="Le Crédit Agricole va fermer sept agences en Haute-Vienne",
            texte="Les agences de Bessines, Ambazac et Nieul seront fermées.",
        )
        geocode_fn = self._make_geocode_fn({"Bessines", "Ambazac", "Nieul"})
        queries = drilldown.requetes_depuis_articles([article], geocode_fn)
        assert any("Bessines" in q for q in queries)
        assert any("Ambazac" in q for q in queries)
        assert any("Nieul" in q for q in queries)
        assert all("Crédit Agricole" in q for q in queries)

    def test_skips_non_plan_articles(self):
        article = self._plan_article(
            titre="Le Crédit Agricole ferme son agence de Tulle",
            texte="L'agence de Tulle sera fermée le mois prochain.",
        )
        geocode_fn = self._make_geocode_fn({"Tulle"})
        queries = drilldown.requetes_depuis_articles([article], geocode_fn)
        assert queries == []

    def test_skips_article_without_bank(self):
        article = self._plan_article(
            titre="Fermeture de sept agences dans la région",
            texte="Les agences de Bessines, Ambazac et Nieul ferment.",
        )
        geocode_fn = self._make_geocode_fn({"Bessines", "Ambazac", "Nieul"})
        queries = drilldown.requetes_depuis_articles([article], geocode_fn)
        assert queries == []

    def test_dedup_across_articles(self):
        article1 = self._plan_article(
            titre="Le Crédit Agricole va fermer sept agences en Haute-Vienne",
            texte="Les agences de Bessines et Ambazac seront fermées.",
        )
        article2 = self._plan_article(
            titre="Le Crédit Agricole ferme plusieurs agences",
            texte="Les agences de Bessines et Nieul seront fermées.",
        )
        geocode_fn = self._make_geocode_fn({"Bessines", "Ambazac", "Nieul"})
        queries = drilldown.requetes_depuis_articles([article1, article2], geocode_fn)
        # "Crédit Agricole fermeture agence Bessines" should appear only once
        bessines_queries = [q for q in queries if "Bessines" in q]
        assert len(bessines_queries) == 1

    def test_respects_max_total(self):
        articles = []
        valid = set()
        for i in range(20):
            commune = f"Commune{i:02d}"
            valid.add(commune)
            articles.append(self._plan_article(
                titre=f"Crédit Agricole ferme plusieurs agences département {i}",
                texte=f"Les agences de {commune} et Ville{i:02d} seront fermées.",
            ))
        geocode_fn = self._make_geocode_fn(valid)
        queries = drilldown.requetes_depuis_articles(articles, geocode_fn, max_total=10)
        assert len(queries) <= 10

    def test_empty_articles(self):
        assert drilldown.requetes_depuis_articles([], lambda c: None) == []
