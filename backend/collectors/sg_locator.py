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
import json
import re
from pathlib import Path
from backend.dedup import closure_id

_MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

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


def _record_to_closure(a: dict) -> dict:
    citation = (f"À compter du {a['date_fermeture']}, l'agence SG de {a['commune']} "
                f"({a.get('adresse', '')}) transfère ses activités vers "
                f"{a.get('destination', '?')}. [TRANSFERT_TOTAL — localisateur officiel SG]")
    return {
        "id": closure_id("Société Générale", a["commune"], "fermeture"),
        "banque": "Société Générale",
        "commune": a["commune"],
        "code_insee": None,
        "departement": a.get("departement"),
        "type": "fermeture",
        "date_annonce": None,
        "date_fermeture": a.get("date_fermeture"),
        "statut": "confirmé",
        "fiabilite": 5,  # Niveau 1 : confirmé officiel
        "statut_temporel": "a_venir",
        "lat": None,
        "lon": None,
        "citation": citation,
        "_adresse": a.get("adresse"),   # utilisé pour le géocodage précis
        "_source_url": a.get("url") or _URL,
    }


def seed_closures() -> list[dict]:
    return [_record_to_closure(a) for a in SEED]


def parse_message(texte: str) -> dict:
    """Extrait {date_fermeture ISO, code_guichet, destination} d'un message SG
    type « À compter du mardi 7 juillet 2026 l'agence de X (02378) transfère son
    activité vers l'agence de Y (02369). »"""
    t = texte or ""
    res = {"date_fermeture": None, "code_guichet": None, "destination": None}
    # Date : "7 juillet 2026" ou "07/07/2026"
    m = re.search(r"(\d{1,2})\s+([a-zA-ZéûôàèA-ZÉ]+)\s+(\d{4})", t)
    if m and m.group(2).lower() in _MOIS:
        res["date_fermeture"] = f"{int(m.group(3)):04d}-{_MOIS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    else:
        m2 = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
        if m2:
            res["date_fermeture"] = f"{m2.group(3)}-{int(m2.group(2)):02d}-{int(m2.group(1)):02d}"
    # Destination : "vers l'agence de Y"
    md = re.search(r"vers l['’]agence de\s+([^()\.]+?)\s*(?:\(|\.|$)", t)
    if md:
        res["destination"] = md.group(1).strip()
    # Codes guichet (premier = agence concernée)
    codes = re.findall(r"\((\d{4,5})\)", t)
    if codes:
        res["code_guichet"] = codes[0]
    return res


def crawled_closures(path) -> list[dict]:
    """Charge les agences détectées par le crawler headless (tools/locator_crawl_sg.py).
    Fichier JSON : liste de {commune, departement, adresse, date_fermeture, destination}."""
    p = Path(path)
    if not p.exists():
        return []
    records = json.loads(p.read_text(encoding="utf-8"))
    return [_record_to_closure(a) for a in records if a.get("commune") and a.get("date_fermeture")]
