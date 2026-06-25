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

def test_article_hors_sujet_reste_rejete():
    # Aucune enseigne, aucun terme de fermeture => doit rester rejeté
    art = {"titre": "Le marché aux fleurs ouvre ce week-end", "texte": ""}
    assert is_relevant(art) is False
