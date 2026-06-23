"""Localisateur Société Générale — fermetures/transferts d'agences à VENIR.

Source publique la plus exploitable aujourd'hui : les fiches du localisateur SG
(agences.sg.fr) affichent, parfois plusieurs semaines à l'avance, une phrase
structurée du type « À compter du JJ/MM/AAAA, votre agence de X transfère ses
activités vers l'agence Y ». Chez SG, « transfère ses activités » = disparition
de l'agence comme point de vente autonome (TRANSFERT_TOTAL).

Ce module fournit :
  - PHRASES : les expressions à détecter sur une fiche ;
  - est_fermeture_future(texte) : détecteur ;
  - SEED : les fermetures SG nominativement vérifiées (Niveau 1, officiel) ;
  - seed_closures() : ces fermetures sous forme de closures prêtes à stocker
    (lat/lon/code_insee/departement remplis ensuite par géocodage de l'adresse).

NB : il n'existe pas de liste publique exhaustive des fermetures futures (cf.
backend/plans.py pour les volumes annoncés non nominatifs). On n'enregistre que
le nominatif vérifié — on n'invente pas d'agences à partir d'un volume global.
"""
import re
from backend.dedup import closure_id

PHRASES = [
    r"(?i)à compter du",
    r"(?i)transfère(?:ra)? ses activités",
    r"(?i)transfère son activité",
    r"(?i)sera rattachée? à",
    r"(?i)fermera définitivement",
    r"(?i)fermeture définitive",
    r"(?i)regroupement avec",
    r"(?i)transfert de votre agence",
]
_PHRASES_C = [re.compile(p) for p in PHRASES]


def est_fermeture_future(texte: str) -> bool:
    t = texte or ""
    return any(rx.search(t) for rx in _PHRASES_C)


# Fermetures SG nominativement vérifiées sur le localisateur officiel.
# operation TRANSFERT_TOTAL (l'agence disparaît comme point de vente autonome).
SEED = [
    {"commune": "Hérouville-Saint-Clair", "departement": "14",
     "adresse": "320 quartier du Val, 14200 Hérouville-Saint-Clair",
     "date_fermeture": "2026-06-23", "destination": "Caen Côte de Nacre"},
    {"commune": "Piégut-Pluviers", "departement": "24",
     "adresse": "11 rue des Alliés, 24360 Piégut-Pluviers",
     "date_fermeture": "2026-07-07", "destination": "Nontron"},
    {"commune": "Strasbourg", "departement": "67",
     "adresse": "267 avenue de Colmar, 67100 Strasbourg",
     "date_fermeture": "2026-07-07", "destination": "Strasbourg Esplanade"},
    {"commune": "Origny-Sainte-Benoite", "departement": "02",
     "adresse": "89 rue Pasteur, 02390 Origny-Sainte-Benoite",
     "date_fermeture": "2026-07-09", "destination": "Saint-Quentin Centre"},
    {"commune": "Bernin", "departement": "38",
     "adresse": "ZAC Les Michellières, 38190 Bernin",
     "date_fermeture": "2026-07-16", "destination": "Saint-Ismier"},
    {"commune": "Paris 19e (Botzaris)", "departement": "75",
     "adresse": "1 rue de Mouzaïa, 75019 Paris",
     "date_fermeture": "2026-07-21", "destination": "Paris Manin / Paris Jourdain"},
]

_URL = "https://agences.sg.fr/"


def seed_closures() -> list[dict]:
    closures = []
    for a in SEED:
        citation = (f"À compter du {a['date_fermeture']}, l'agence SG de {a['commune']} "
                    f"({a['adresse']}) transfère ses activités vers {a['destination']}. "
                    f"[TRANSFERT_TOTAL — localisateur officiel SG]")
        closures.append({
            "id": closure_id("Société Générale", a["commune"], "fermeture"),
            "banque": "Société Générale",
            "commune": a["commune"],
            "code_insee": None,
            "departement": a["departement"],
            "type": "fermeture",
            "date_annonce": None,
            "date_fermeture": a["date_fermeture"],
            "statut": "confirmé",
            "fiabilite": 5,  # Niveau 1 : confirmé officiel
            "lat": None,
            "lon": None,
            "citation": citation,
            "_adresse": a["adresse"],   # utilisé pour le géocodage précis
            "_source_url": _URL,
        })
    return closures
