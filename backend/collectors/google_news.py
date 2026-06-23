import urllib.parse
import feedparser
import requests

# Le scoping par département du flux RSS Google News est inopérant (il renvoie
# un même lot national dupliqué). On interroge donc par requêtes nationales
# thématiques ; l'extraction IA déduit ensuite le département de chaque article.
QUERIES = [
    "fermeture agence bancaire",
    "banque ferme agence",
    "fusion agences bancaires",
    "agence bancaire ferme ses portes",
    "regroupement agences bancaires",
]


def _feed_url(query: str) -> str:
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
