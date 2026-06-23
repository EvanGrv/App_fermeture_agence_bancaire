import feedparser
import requests
import config

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; veille-presse/1.0; "
        "+https://localhost/flux-publics-non-commercial)"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
}


def parse_feed(xml: str, source_label: str) -> list[dict]:
    parsed = feedparser.parse(xml)
    articles = []
    for entry in parsed.entries:
        articles.append({
            "titre": entry.get("title", ""),
            "texte": entry.get("description", "") or entry.get("summary", ""),
            "url": entry.get("link", ""),
            "date": entry.get("published", "") or entry.get("updated", ""),
            "source": source_label,
            "departement": None,
        })
    return articles


def _default_fetch(url: str) -> str:
    resp = requests.get(url, timeout=30, headers=_HEADERS)
    resp.raise_for_status()
    return resp.text


def collect(fetch=_default_fetch, feeds=None) -> list[dict]:
    resultats = []
    vus = set()
    for feed in feeds or config.LOCAL_RSS_FEEDS:
        label = feed["label"]
        url = feed["url"]
        try:
            xml = fetch(url)
        except Exception as exc:
            print(f"[local_feeds] {label}: erreur {exc}")
            continue
        for art in parse_feed(xml, label):
            art_url = art.get("url") or ""
            if art_url and art_url in vus:
                continue
            if art_url:
                vus.add(art_url)
            resultats.append(art)
    return resultats
