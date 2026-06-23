"""Plans nationaux de fermeture ANNONCÉS mais NON nominatifs.

Volumes globaux communiqués (presse/syndicats) sans liste publique d'agences.
On les garde dans une table distincte : on ne fabrique pas les agences concernées
à partir d'un volume. Sert de contexte/veille, pas de points sur la carte.
"""

PLANS = [
    {"banque": "Société Générale", "volume": 101, "echeance": "2026",
     "liste_publique": False,
     "note": "Chiffre CGT ; la direction n'a pas confirmé publiquement."},
    {"banque": "CCF", "volume": 72, "echeance": "fin 2026",
     "liste_publique": False,
     "note": "Plan ramené à 72 après négociation ; liste nominative non publique."},
    {"banque": "BNP Paribas", "volume": 500, "echeance": "2030",
     "liste_publique": False,
     "note": "Réduction progressive évoquée (~500) ; pas de calendrier nominatif."},
]
