import time
import urllib.parse
import requests

_QUERY = '(agence banque) (fermeture OR fusion) sourcelang:french'
_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
_TIMESPAN = "6m"  # GDELT : m = mois ici (≠ Google News) → 6 mois
_MIN_INTERVAL = 5.0  # GDELT exige 1 requête / 5 s


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


def collect(fetch=_default_fetch, retries=4, base_wait=6.0) -> list[dict]:
    # GDELT impose 1 requête / 5 s par IP (429 + message texte). On respecte
    # l'intervalle, on honore Retry-After, et on backoff en cas de pénalité.
    wait = base_wait
    for tentative in range(retries + 1):
        try:
            return parse_response(fetch(_url()))
        except requests.exceptions.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if tentative >= retries:
                print(f"[gdelt] abandon après {retries} tentatives (HTTP {status})")
                return []
            pause = wait
            if status == 429:
                ra = exc.response.headers.get("Retry-After", "") if exc.response else ""
                if ra.isdigit():
                    pause = max(float(ra), _MIN_INTERVAL)
                print(f"[gdelt] 429 rate-limit — attente {pause:.0f}s (tentative {tentative + 1}/{retries})")
            time.sleep(max(pause, _MIN_INTERVAL))
            wait *= 1.5
        except Exception as exc:
            if tentative >= retries:
                print(f"[gdelt] erreur {exc}")
                return []
            time.sleep(wait)
            wait *= 1.5
    return []
