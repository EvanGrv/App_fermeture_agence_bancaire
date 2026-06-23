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
