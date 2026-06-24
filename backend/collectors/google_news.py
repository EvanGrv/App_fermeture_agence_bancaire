import urllib.parse
import feedparser
import requests
import config

# Le scoping par département du flux RSS Google News est inopérant (il renvoie
# un même lot national dupliqué). On interroge donc par requêtes nationales :
# des requêtes thématiques + une requête par enseigne (chaque flux plafonne à
# ~100 résultats, donc multiplier les angles maximise la couverture). L'extraction
# IA déduit ensuite le département de chaque article ; la dédup se fait par URL.
_THEMATIQUES = [
    "fermeture agence bancaire",
    "banque ferme agence",
    "fusion agences bancaires",
    "agence bancaire ferme ses portes",
    "regroupement agences bancaires",
    "fermeture agence banque",
    "désert bancaire fermeture agence",
]
_PAR_ENSEIGNE = (
    [f"{e} fermeture agence" for e in config.ENSEIGNES]
    + [f"{e} ferme agence" for e in config.ENSEIGNES]
)
_MARQUES_REGIONALES = [
    f"{variante} fermeture agence"
    for variantes in getattr(config, "MARQUES_REGIONALES", {}).values()
    for variante in variantes
]
_REGIONS = [
    "Auvergne-Rhône-Alpes",
    "Bourgogne-Franche-Comté",
    "Bretagne",
    "Centre-Val de Loire",
    "Corse",
    "Grand Est",
    "Hauts-de-France",
    "Île-de-France",
    "Normandie",
    "Nouvelle-Aquitaine",
    "Occitanie",
    "Pays de la Loire",
    "Provence-Alpes-Côte d'Azur",
]
_PAR_REGION = [
    f"{theme} {region}"
    for region in _REGIONS
    for theme in (
        "fermeture agence bancaire",
        "Crédit Agricole fermeture agence",
        "Société Générale fermeture agence",
        "BNP Paribas fermeture agence",
        "Caisse d'Épargne fermeture agence",
    )
]
_PAR_DEPARTEMENT = [
    f"fermeture agence bancaire {nom}"
    for nom in getattr(config, "DEPARTEMENTS", {}).values()
]
_PRESSE_REGIONALE = [
    f"site:{domaine} fermeture agence bancaire"
    for domaine in (
        "actu.fr",
        "ouest-france.fr",
        "ladepeche.fr",
        "ledauphine.com",
        "estrepublicain.fr",
        "republicain-lorrain.fr",
        "sudouest.fr",
        "lanouvellerepublique.fr",
        "paris-normandie.fr",
        "lavoixdunord.fr",
        "francebleu.fr",
        "ici.fr",
    )
]
QUERIES = list(dict.fromkeys(
    _THEMATIQUES
    + _PAR_ENSEIGNE
    + _MARQUES_REGIONALES
    + _PAR_REGION
    + _PAR_DEPARTEMENT
    + _PRESSE_REGIONALE
))


def _feed_url(query: str) -> str:
    fenetre = getattr(config, "GOOGLE_NEWS_WHEN", "")
    if fenetre:
        query = f"{query} when:{fenetre}"
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=fr&gl=FR&ceid=FR:fr"


def parse_feed(xml: str, source_label: str = "Google News") -> list[dict]:
    parsed = feedparser.parse(xml)
    articles = []
    for entry in parsed.entries:
        articles.append({
            "titre": entry.get("title", ""),
            "texte": entry.get("description", ""),
            "url": entry.get("link", ""),
            "date": entry.get("published", ""),
            "source": source_label,
            "departement": None,
        })
    return articles


def _default_fetch(url: str) -> str:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "veille-presse/1.0"})
    resp.raise_for_status()
    return resp.text


def collect(fetch=_default_fetch, queries=QUERIES) -> list[dict]:
    resultats = []
    vus = set()
    for query in queries:
        try:
            xml = fetch(_feed_url(query))
        except Exception as exc:  # une source en panne ne casse pas le run
            print(f"[google_news] requête '{query}': erreur {exc}")
            continue
        for art in parse_feed(xml):
            url = art.get("url") or ""
            if url and url in vus:
                continue
            if url:
                vus.add(url)
            resultats.append(art)
    return resultats
