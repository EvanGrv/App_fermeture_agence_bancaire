import urllib.parse
import feedparser
import requests
import config

_ENSEIGNES_OR = " OR ".join(f'"{e}"' for e in config.ENSEIGNES)
_TERMES_OR = " OR ".join(["fermeture", "fermée", "fusion", "regroupement"])


def build_query(departement_nom: str) -> str:
    return f'({_ENSEIGNES_OR}) ({_TERMES_OR}) agence "{departement_nom}"'


def _feed_url(departement_nom: str) -> str:
    q = urllib.parse.quote(build_query(departement_nom))
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


def collect(fetch=_default_fetch) -> list[dict]:
    resultats = []
    for code, nom in config.DEPARTEMENTS.items():
        try:
            xml = fetch(_feed_url(nom))
        except Exception as exc:  # une source en panne ne casse pas le run
            print(f"[google_news] {code} {nom}: erreur {exc}")
            continue
        for art in parse_feed(xml):
            art["departement"] = code
            resultats.append(art)
    return resultats
