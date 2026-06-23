import time
import urllib.parse
import requests

_QUERY = '(agence banque) (fermeture OR fusion) sourcelang:french'
_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
_TIMESPAN = "6m"  # GDELT : m = mois ici (≠ Google News) → 6 mois


def parse_response(payload: dict) -> list[dict]:
    articles = []
    for item in payload.get("articles", []):
        articles.append({
            "titre": item.get("title", ""),
            "texte": "",
            "url": item.get("url", ""),
            "date": item.get("seendate", ""),
            "source": "GDELT",
            "departement": None,
        })
    return articles


def _url() -> str:
    params = urllib.parse.urlencode({
        "query": _QUERY, "mode": "ArtList", "format": "json",
        "maxrecords": "250", "timespan": _TIMESPAN,
    })
    return f"{_BASE}?{params}"


def _default_fetch(url: str) -> dict:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "veille-presse/1.0"})
    resp.raise_for_status()
    return resp.json()


def collect(fetch=_default_fetch, retries=3, backoff=8.0) -> list[dict]:
    # GDELT renvoie souvent 429/HTML transitoire : on retente avec backoff.
    for tentative in range(retries + 1):
        try:
            return parse_response(fetch(_url()))
        except Exception as exc:
            if tentative < retries:
                time.sleep(backoff)
                continue
            print(f"[gdelt] erreur {exc}")
            return []
    return []
