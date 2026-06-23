from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
EXPORT_DIR = DATA_DIR / "export"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "press.db"
DATA_JSON = EXPORT_DIR / "data.json"
GEOJSON_PATH = EXPORT_DIR / "departements.geojson"

# Modèle IA d'extraction (le plus capable par défaut). claude-haiku-4-5 = option moins chère pour le volume.
ANTHROPIC_MODEL = "claude-opus-4-8"

# Fenêtre de récence appliquée aux requêtes Google News (opérateur `when:`).
# ATTENTION aux unités Google News : h=heures, d=jours, y=années (m=MINUTES, pas mois).
# Donc 1 mois = "30d", 2 semaines = "14d", 6 mois = "180d", 1 an = "1y".
GOOGLE_NEWS_WHEN = "180d"

ENSEIGNES = [
    "Crédit Agricole", "BNP", "Société Générale", "Banque Populaire",
    "Caisse d'Épargne", "Crédit Mutuel", "CIC", "LCL",
    "Crédit du Nord", "HSBC", "CCF",
]

# Principales marques régionales ou anciennes dénominations utiles pour la
# presse locale. Elles sont rattachées à une enseigne canonique dans l'extracteur.
MARQUES_REGIONALES = {
    "Crédit Agricole": [
        "Crédit Agricole Alpes Provence",
        "Crédit Agricole Alsace Vosges",
        "Crédit Agricole Anjou Maine",
        "Crédit Agricole Atlantique Vendée",
        "Crédit Agricole Brie Picardie",
        "Crédit Agricole Centre-Est",
        "Crédit Agricole Centre France",
        "Crédit Agricole Centre Loire",
        "Crédit Agricole Charente-Maritime Deux-Sèvres",
        "Crédit Agricole des Savoie",
        "Crédit Agricole Finistère",
        "Crédit Agricole Franche-Comté",
        "Crédit Agricole Ille-et-Vilaine",
        "Crédit Agricole Languedoc",
        "Crédit Agricole Loire Haute-Loire",
        "Crédit Agricole Lorraine",
        "Crédit Agricole Normandie",
        "Crédit Agricole Normandie-Seine",
        "Crédit Agricole Nord de France",
        "Crédit Agricole Pyrénées Gascogne",
        "Crédit Agricole Sud Rhône Alpes",
        "CA Centre-Est",
        "CA Loire Haute-Loire",
    ],
    "Société Générale": [
        "SG",
        "SG SMC",
        "SG Courtois",
        "SG Laydernier",
        "SG Tarneaud",
        "SG Crédit du Nord",
        "Banque Courtois",
        "Banque Laydernier",
        "Banque Tarneaud",
        "Banque Kolb",
        "Banque Rhône-Alpes",
    ],
    "Crédit Mutuel": [
        "Crédit Mutuel Alliance Fédérale",
        "Crédit Mutuel Arkéa",
        "Crédit Mutuel de Bretagne",
        "Crédit Mutuel du Sud-Ouest",
        "Crédit Mutuel Massif Central",
        "Crédit Mutuel Nord Europe",
        "CMB",
        "CMSO",
    ],
    "Banque Populaire": [
        "Banque Populaire Auvergne Rhône Alpes",
        "Banque Populaire Bourgogne Franche-Comté",
        "Banque Populaire Grand Ouest",
        "Banque Populaire Méditerranée",
        "Banque Populaire Occitane",
        "Banque Populaire Rives de Paris",
        "Banque Populaire Val de France",
        "BPGO",
        "BPALC",
        "BRED",
    ],
    "Caisse d'Épargne": [
        "Caisse d'Épargne Aquitaine Poitou-Charentes",
        "Caisse d'Épargne Auvergne Limousin",
        "Caisse d'Épargne Bourgogne Franche-Comté",
        "Caisse d'Épargne Bretagne Pays de Loire",
        "Caisse d'Épargne Côte d'Azur",
        "Caisse d'Épargne Grand Est Europe",
        "Caisse d'Épargne Hauts de France",
        "Caisse d'Épargne Île-de-France",
        "Caisse d'Épargne Languedoc-Roussillon",
        "Caisse d'Épargne Loire Centre",
        "Caisse d'Épargne Loire Drôme Ardèche",
        "Caisse d'Épargne Midi-Pyrénées",
        "Caisse d'Épargne Normandie",
        "Caisse d'Épargne Rhône Alpes",
        "CEBPL",
        "CEGEE",
        "CELC",
    ],
}

# Enseignes explicitement exclues du suivi (formes normalisées).
EXCLURE_BANQUES = ["la banque postale", "banque postale"]

TERMES_FERMETURE = [
    "fermeture", "ferme", "fermer", "fermé", "fusion", "fusionne",
    "regroupement", "regroupe", "supprime", "suppression", "transfert",
]

# Flux RSS publics de presse/radio locale. Ils complètent Google News en
# captant directement les dernières publications des grands réseaux régionaux.
LOCAL_RSS_FEEDS = [
    {"label": "Actu.fr", "url": "https://actu.fr/rss.xml"},
    {"label": "Ouest-France", "url": "https://www.ouest-france.fr/rss/france"},
    {"label": "Ici", "url": "https://www.ici.fr/rss/infos.xml"},
    {"label": "La Dépêche", "url": "https://www.ladepeche.fr/rss.xml"},
]

# Codes département → nom (métropole + DROM). Liste complète requise.
DEPARTEMENTS = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes",
    "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron",
    "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud",
    "2B": "Haute-Corse", "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse",
    "24": "Dordogne", "25": "Doubs", "26": "Drôme", "27": "Eure", "28": "Eure-et-Loir",
    "29": "Finistère", "30": "Gard", "31": "Haute-Garonne", "32": "Gers",
    "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine", "36": "Indre",
    "37": "Indre-et-Loire", "38": "Isère", "39": "Jura", "40": "Landes",
    "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire", "44": "Loire-Atlantique",
    "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne", "48": "Lozère",
    "49": "Maine-et-Loire", "50": "Manche", "51": "Marne", "52": "Haute-Marne",
    "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse", "56": "Morbihan",
    "57": "Moselle", "58": "Nièvre", "59": "Nord", "60": "Oise", "61": "Orne",
    "62": "Pas-de-Calais", "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques",
    "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales", "67": "Bas-Rhin",
    "68": "Haut-Rhin", "69": "Rhône", "70": "Haute-Saône", "71": "Saône-et-Loire",
    "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie", "75": "Paris",
    "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres",
    "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse",
    "85": "Vendée", "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne",
    "90": "Territoire de Belfort", "91": "Essonne", "92": "Hauts-de-Seine",
    "93": "Seine-Saint-Denis", "94": "Val-de-Marne", "95": "Val-d'Oise",
    "971": "Guadeloupe", "972": "Martinique", "973": "Guyane", "974": "La Réunion",
    "976": "Mayotte",
}
