from backend.prefilter import is_relevant

def test_garde_article_pertinent():
    art = {"titre": "La Société Générale ferme son agence",
           "texte": "L'agence de Rennes va fermer en juin."}
    assert is_relevant(art) is True

def test_rejette_sans_enseigne():
    art = {"titre": "Fermeture d'une boulangerie", "texte": "Le commerce ferme."}
    assert is_relevant(art) is False

def test_rejette_sans_terme_fermeture():
    art = {"titre": "Le Crédit Agricole recrute", "texte": "Nouvelle embauche."}
    assert is_relevant(art) is False

def test_insensible_accents_casse():
    art = {"titre": "CREDIT MUTUEL", "texte": "agence fermee a Brest"}
    assert is_relevant(art) is True

def test_marque_regionale_avec_euphemisme_est_pertinente():
    # "Banque Kolb" est une marque SG régionale ; "rideau" est un nouvel euphémisme
    art = {"titre": "La Banque Kolb baisse le rideau à Saint-Dié", "texte": ""}
    assert is_relevant(art) is True

def test_euphemisme_cesse_activite_est_pertinent():
    # "cesse" est un nouvel euphémisme ; Société Générale est une enseigne nationale
    art = {"titre": "La Société Générale cesse son activité dans cette agence", "texte": ""}
    assert is_relevant(art) is True


def test_banque_postale_prevision_fermera_est_pertinente():
    art = {
        "titre": "La Banque Postale fermera son agence de Tulle",
        "texte": "La fermeture est prévue l'an prochain.",
    }
    assert is_relevant(art) is True


def test_banque_postale_services_financiers_bureau_de_poste():
    art = {
        "titre": "La Banque Postale: menace de fermeture au bureau de poste",
        "texte": "Les habitants craignent la perte des services financiers.",
    }
    assert is_relevant(art) is True

def test_article_hors_sujet_reste_rejete():
    # Aucune enseigne, aucun terme de fermeture => doit rester rejeté
    art = {"titre": "Le marché aux fleurs ouvre ce week-end", "texte": ""}
    assert is_relevant(art) is False


# --- Fix 1: tighten over-broad prefilter stems ---

def test_quitte_fonctions_non_pertinent():
    # Le bare stem "quitte" captait des départs de dirigeants sans lien avec une fermeture.
    # Après le fix, seule la forme précise "quitte la commune" reste pertinente.
    art = {"titre": "Le directeur de la BNP quitte ses fonctions", "texte": ""}
    assert is_relevant(art) is False


def test_quittera_la_commune_reste_pertinent():
    # La forme précise "quittera la commune" (euphémisme de fermeture) doit rester capturée.
    art = {"titre": "Le Crédit Agricole quittera la commune de Tulle", "texte": ""}
    assert is_relevant(art) is True


# --- Cycle 2b: analyse() — scoring + entité-detection ---

from backend.prefilter import analyse, PrefilterResult


def test_analyse_titre_banque_fermeture_score_haut():
    r = analyse({"titre": "La Société Générale ferme son agence de Rennes",
                 "texte": "L'agence de Rennes fermera le 30 juin 2026."})
    assert isinstance(r, PrefilterResult)
    assert r.score >= 3
    assert r.banks  # au moins une banque détectée
    assert r.compact_context == ""  # rempli plus tard par le pipeline


def test_analyse_phrase_banque_commune_fermeture():
    r = analyse({"titre": "Réseau bancaire",
                 "texte": "Le Crédit Agricole va fermer son agence de Tulle cet été."})
    assert r.score >= 3
    assert any("Tulle" in c for c in r.communes)


def test_analyse_liste_communes_bonus():
    r = analyse({"titre": "Crédit Agricole réorganise",
                 "texte": "Les agences de Bessines, Saint-Junien et Tulle vont fermer."})
    assert len(r.communes) >= 2
    assert r.score >= 2


def test_analyse_date_detectee():
    r = analyse({"titre": "BNP ferme une agence",
                 "texte": "La fermeture est prévue pour le 1er septembre 2026 à Lyon."})
    assert r.dates
    assert r.score >= 2


def test_analyse_adresse_detectee():
    r = analyse({"titre": "LCL ferme",
                 "texte": "L'agence LCL du 12 rue de la République, 69001 Lyon fermera."})
    assert r.addresses


def test_analyse_rh_sans_agence_penalise():
    r = analyse({"titre": "Plan social à la BNP",
                 "texte": "Suppression de postes et licenciements ; grève des salariés."})
    assert r.score <= -2, f"score={r.score}"


def test_analyse_hors_sujet_penalise():
    r = analyse({"titre": "Le marché aux fleurs ouvre", "texte": "Beau temps ce week-end."})
    assert r.score <= -3


def test_is_relevant_toujours_present():
    # compat : le booléen historique reste exposé et inchangé
    assert analyse and callable(analyse)
    from backend.prefilter import is_relevant
    assert is_relevant({"titre": "Société Générale ferme", "texte": "agence"}) is True


# --- Fix A: word-boundary department detection ---

def test_analyse_departements_word_boundary():
    # "Saint-Denis" must NOT yield "01" (Ain contains "ain" substring of "Saint")
    # "demain" must NOT yield "01" (Ain would match as substring)
    r = analyse({"titre": "À Saint-Denis, on agit demain",
                 "texte": "La BNP ferme son agence. Rendez-vous demain à Saint-Denis."})
    assert "01" not in r.departements, f"false positive Ain via substring: {r.departements}"

    # "La Réunion" should yield "974"
    r2 = analyse({"titre": "Société Générale ferme à La Réunion",
                  "texte": "L'agence de Saint-Denis de La Réunion ferme."})
    assert "974" in r2.departements, f"974 not found: {r2.departements}"

    # parenthesised 3-digit DOM code "(974)" should yield "974"
    r3 = analyse({"titre": "Fermetures d'agences BNP",
                  "texte": "Les agences (974) et (59) sont concernées."})
    assert "59" in r3.departements, f"59 not found: {r3.departements}"
    assert "974" in r3.departements, f"974 not found via code: {r3.departements}"
