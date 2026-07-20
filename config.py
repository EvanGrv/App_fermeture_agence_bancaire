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

# Référentiel La Banque Postale : source CSV optionnelle. Si aucune URL n'est
# fournie, le pipeline lit data/cache/lbp_agences.csv quand il existe.
LBP_AGENCES_CSV_URL = os.getenv("LBP_AGENCES_CSV_URL", "")
LBP_AGENCES_CACHE = CACHE_DIR / "lbp_agences.csv"

# Modèles IA d'extraction : Haiku traite le volume, Sonnet sert de filet pour
# les cas ambigus. Surcharge possible via .env.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
ANTHROPIC_FALLBACK_MODEL = os.getenv("ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-4-6")
ANTHROPIC_FALLBACK_ENABLED = os.getenv("ANTHROPIC_FALLBACK_ENABLED", "1") != "0"

# Cache d'extraction IA (Cycle 2a) : ne jamais relancer l'IA sur un contenu déjà
# extrait pour (content_hash, extraction_version, model). Bump EXTRACTION_VERSION
# quand le prompt ou le schéma d'extraction change (invalidation propre).
EXTRACTION_VERSION = int(os.getenv("EXTRACTION_VERSION", "5"))
EXTRACTION_MAX_ATTEMPTS = int(os.getenv("EXTRACTION_MAX_ATTEMPTS", "3"))
EXTRACTION_RETRY_BASE_MIN = int(os.getenv("EXTRACTION_RETRY_BASE_MIN", "60"))
STRUCTURED_SONNET_ESCALATION_ENABLED = (
    os.getenv("STRUCTURED_SONNET_ESCALATION_ENABLED", "1") != "0"
)
STRUCTURED_SONNET_MIN_CONFIDENCE = float(
    os.getenv("STRUCTURED_SONNET_MIN_CONFIDENCE", "0.65")
)

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
# La file est plafonnée par run pour maîtriser le nombre de recherches web. Le
# coût IA est contrôlé séparément par VIGILANCE_REVIEW_AI_ENABLED.
VIGILANCE_REVIEW_MAX_PER_RUN = int(os.getenv("VIGILANCE_REVIEW_MAX_PER_RUN", "6"))
VIGILANCE_REVIEW_MAX_QUERIES_PER_ITEM = int(
    os.getenv("VIGILANCE_REVIEW_MAX_QUERIES_PER_ITEM", "3"))
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

# Observation officielle du réseau La Poste. La liste nationale est légère
# (~20 000 points) et versionnée côté producteur; une révision déjà traitée est
# ignorée. Le calendrier bancaire n'est interrogé que pour les points LBP déjà
# identifiés par un article ou un changement du réseau.
LAPOSTE_OPEN_DATA_ENABLED = os.getenv("LAPOSTE_OPEN_DATA_ENABLED", "1") != "0"
LAPOSTE_POINTS_DATASET_ID = os.getenv("LAPOSTE_POINTS_DATASET_ID", "laposte-poincont2")
LAPOSTE_CALENDAR_DATASET_ID = os.getenv(
    "LAPOSTE_CALENDAR_DATASET_ID", "tjwztt6h44ve52i7fln6rbxz")
LAPOSTE_DATA_API_BASE = os.getenv(
    "LAPOSTE_DATA_API_BASE", "https://data.laposte.fr/data-fair/api/v1/datasets")
LAPOSTE_MISSING_CONFIRMATIONS = int(os.getenv("LAPOSTE_MISSING_CONFIRMATIONS", "2"))
LAPOSTE_CALENDAR_MAX_CHECKS = int(os.getenv("LAPOSTE_CALENDAR_MAX_CHECKS", "20"))

# Recherche web spécialisée bureaux de poste. Le budget par défaut est plafonné
# à 8 requêtes par run; l'accès Brave reste optionnel et dépend de son offre.
POSTAL_WEB_ENABLED = os.getenv("POSTAL_WEB_ENABLED", "1") != "0"
POSTAL_WEB_MAX_QUERIES = int(os.getenv("POSTAL_WEB_MAX_QUERIES", "8"))

# Backfill LBP spécialisé. Il ne s'exécute que lorsque la fenêtre demandée est
# suffisamment profonde (le workflow hebdomadaire utilise environ 720 jours).
POSTAL_HISTORY_ENABLED = os.getenv("POSTAL_HISTORY_ENABLED", "1") != "0"
POSTAL_HISTORY_MIN_DAYS = int(os.getenv("POSTAL_HISTORY_MIN_DAYS", "700"))
POSTAL_HISTORY_WEB_MAX_QUERIES = int(
    os.getenv("POSTAL_HISTORY_WEB_MAX_QUERIES", "12")
)

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
        "Crédit Agricole Centre Ouest",
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
    "va fermer", "vont fermer", "fermera", "fermeront",
    "doit fermer", "doivent fermer", "pourrait fermer", "pourraient fermer",
    "menace de fermeture", "menacé de fermeture", "menacée de fermeture",
    "fermeture définitive", "définitivement fermé", "définitivement fermée",
    "transformation", "transformé en", "transformée en", "devient une agence postale",
    "remplacé par", "remplacée par", "relais poste", "relais postal",
]

# Canal La Banque Postale : les fermetures sont souvent formulées comme des
# fermetures de bureaux de poste plutôt que comme des fermetures d'agences
# bancaires. Ces termes ouvrent le préfiltre, puis l'extraction qualifie le
# caractère bancaire.
POSTAL_POINT_TERMS = [
    "bureau de poste", "bureaux de poste", "guichet postal",
    "point de contact postal", "point postal", "la poste",
]
POSTAL_BANKING_TERMS = [
    "banque postale", "la banque postale", "services financiers",
    "service bancaire", "services bancaires", "conseiller bancaire",
    "conseillers bancaires", "gestion de comptes", "retrait d'espèces",
    "dépôt d'espèces", "depots d'especes", "dab banque postale",
]

# Termes RH/social : servent au malus de préfiltre (-2) quand ils apparaissent
# SANS le mot "agence" (article social sans fermeture d'agence identifiée).
RH_TERMS = [
    "licenciement", "plan social", "pse", "suppression de postes", "emplois",
    "syndicat", "greve", "salaries",
]

# Contexte compact envoyé à l'IA (Cycle 2b) : plafond de caractères.
PREFILTER_CONTEXT_MAX_CHARS = int(os.getenv("PREFILTER_CONTEXT_MAX_CHARS", "8000"))

# Gate de préfiltre : on ne saute l'IA que si le score est <= ce seuil (conservateur).
# Les articles sautés sont routés en vigilance (jamais perdus).
PREFILTER_MIN_SCORE = int(os.getenv("PREFILTER_MIN_SCORE", "-2"))

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
