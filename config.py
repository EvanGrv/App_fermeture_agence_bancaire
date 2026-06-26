import os
from pathlib import Path
from backend.env import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
DATA_DIR = ROOT / "data"
EXPORT_DIR = DATA_DIR / "export"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "press.db"
DATA_JSON = EXPORT_DIR / "data.json"
GEOJSON_PATH = EXPORT_DIR / "departements.geojson"

# Modèles IA d'extraction : Haiku traite le volume, Sonnet sert de filet pour
# les cas ambigus. Surcharge possible via .env.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
ANTHROPIC_FALLBACK_MODEL = os.getenv("ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-4-6")
ANTHROPIC_FALLBACK_ENABLED = os.getenv("ANTHROPIC_FALLBACK_ENABLED", "1") != "0"

# Fenêtre de récence appliquée aux requêtes Google News (opérateur `when:`).
# ATTENTION aux unités Google News : h=heures, d=jours, y=années (m=MINUTES, pas mois).
# Donc 1 mois = "30d", 2 semaines = "14d", 6 mois = "180d", 1 an = "1y".
GOOGLE_NEWS_WHEN = os.getenv("GOOGLE_NEWS_WHEN", "180d")

# Fenêtre de veille par défaut : 18 mois glissants (couvre le rétrospectif
# depuis ~début 2025 + le prévisionnel). Élargissable via --lookback-months.
LOOKBACK_MONTHS_DEFAULT = int(os.getenv("LOOKBACK_MONTHS_DEFAULT", "18"))

# Revue arborescente des vigilances : chaque vigilance d'un score suffisant
# devient le point de départ d'une recherche secondaire ciblée (Phase 2).
VIGILANCE_REVIEW_ENABLED = os.getenv("VIGILANCE_REVIEW_ENABLED", "1") != "0"
VIGILANCE_REVIEW_MIN_SCORE = int(os.getenv("VIGILANCE_REVIEW_MIN_SCORE", "3"))
# Par défaut on passe toute la file qualifiée en revue. Le coût IA est contrôlé
# séparément par VIGILANCE_REVIEW_AI_ENABLED.
VIGILANCE_REVIEW_MAX_PER_RUN = int(os.getenv("VIGILANCE_REVIEW_MAX_PER_RUN", "1000"))
VIGILANCE_REVIEW_MAX_QUERIES_PER_ITEM = int(
    os.getenv("VIGILANCE_REVIEW_MAX_QUERIES_PER_ITEM", "8"))
# Solution économique : la revue exploite d'abord titre/source/géocodage et ne
# consomme pas Anthropic par défaut. Activer ponctuellement avec
# VIGILANCE_REVIEW_AI_ENABLED=1 pour une campagne IA complète.
VIGILANCE_REVIEW_AI_ENABLED = os.getenv("VIGILANCE_REVIEW_AI_ENABLED", "0") == "1"
# Intervalle minimal avant de re-réviser une même vigilance (jours).
VIGILANCE_REVIEW_COOLDOWN_DAYS = int(os.getenv("VIGILANCE_REVIEW_COOLDOWN_DAYS", "7"))

# Éclatement des articles "plan multi-agences" en fermetures individuelles (Phase 3).
PLAN_EXPLOSION_ENABLED = os.getenv("PLAN_EXPLOSION_ENABLED", "1") != "0"
PLAN_EXPLOSION_MAX_COMMUNES = int(os.getenv("PLAN_EXPLOSION_MAX_COMMUNES", "30"))

# Provider local_sitemap (Phase 6.3) : découverte web sans clé via sitemaps/feeds.
# Coûteux (multi-fetch HTTP) et non encore optimisé -> DÉSACTIVÉ par défaut pour
# le run quotidien. À activer ponctuellement (LOCAL_SITEMAP_ENABLED=1) pour des
# campagnes ciblées. Timeout court + cache + plafond de domaines par requête.
LOCAL_SITEMAP_ENABLED = os.getenv("LOCAL_SITEMAP_ENABLED", "0") != "0"
LOCAL_SITEMAP_TIMEOUT = int(os.getenv("LOCAL_SITEMAP_TIMEOUT", "5"))
LOCAL_SITEMAP_MAX_DOMAINS = int(os.getenv("LOCAL_SITEMAP_MAX_DOMAINS", "2"))

ENSEIGNES = [
    "Crédit Agricole", "BNP", "Société Générale", "Banque Populaire",
    "Caisse d'Épargne", "Crédit Mutuel", "CIC", "LCL",
    "Crédit du Nord", "HSBC", "CCF", "La Banque Postale", "Crédit Coopératif",
]

# Périmètre optionnel : le Crédit Municipal (ex. Dijon) n'est pas suivi par
# défaut. Activable via INCLUDE_CREDIT_MUNICIPAL=1 (Phase 9).
INCLUDE_CREDIT_MUNICIPAL = os.getenv("INCLUDE_CREDIT_MUNICIPAL", "0") != "0"
if INCLUDE_CREDIT_MUNICIPAL:
    ENSEIGNES.append("Crédit Municipal")

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
        "Crédit Agricole de Franche-Comté",
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
EXCLURE_BANQUES = []

TERMES_FERMETURE = [
    "fermeture", "ferme", "fermer", "fermé", "fusion", "fusionne",
    "regroupement", "regroupe", "supprime", "suppression", "transfert",
    "rideau", "cesse", "cessation", "rattach", "réorganis", "reorganis",
    "libre-service", "libre service",
    "ferme ses portes", "n'accueillera",
    "quittera la commune", "quitte la commune",
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
