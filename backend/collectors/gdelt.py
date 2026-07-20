import os
import time
import urllib.parse
import requests

_QUERY = (
    '((agence banque) OR "La Banque Postale" OR "Banque Postale" '
    'OR "bureau de poste" OR "bureaux de poste") '
    '(fermeture OR fusion OR fermera OR "va fermer" OR "menace de fermeture") '
    'sourcelang:french'
)
_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
_TIMESPAN = os.getenv("GDELT_TIMESPAN", "6m")  # GDELT : m = mois ici (≠ Google News) → 6 mois
_MIN_INTERVAL = 5.0  # GDELT exige 1 requête / 5 s
_LAST_REQUEST_AT = 0.0


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


def _url(timespan: str | None = None) -> str:
    params = urllib.parse.urlencode({
        "query": _QUERY, "mode": "ArtList", "format": "json",
        "maxrecords": "250", "timespan": timespan or _TIMESPAN,
    })
    return f"{_BASE}?{params}"


def _default_fetch(url: str) -> dict:
    global _LAST_REQUEST_AT
    throttle = max(_MIN_INTERVAL, _float_env("GDELT_THROTTLE_SECONDS", 12.0))
    elapsed = time.monotonic() - _LAST_REQUEST_AT
    if elapsed < throttle:
        time.sleep(throttle - elapsed)
    resp = requests.get(url, timeout=30, headers={"User-Agent": "veille-presse/1.0"})
    _LAST_REQUEST_AT = time.monotonic()
    resp.raise_for_status()
    return resp.json()


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def collect(fetch=_default_fetch, retries=2, base_wait=30.0, timespan: str | None = None) -> list[dict]:
    # GDELT impose 1 requête / 5 s par IP (429 + message texte). On respecte
    # l'intervalle, on honore Retry-After, et on backoff en cas de pénalité.
    wait = base_wait
    for tentative in range(retries + 1):
        try:
            return parse_response(fetch(_url(timespan)))
        except requests.exceptions.HTTPError as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            if tentative >= retries:
                print(f"[gdelt] rate-limit persistant (HTTP {status}) — collecteur ignoré pour ce run")
                return []
            pause = wait
            if status == 429:
                ra = response.headers.get("Retry-After", "") if response is not None else ""
                try:
                    pause = max(float(ra), pause, _MIN_INTERVAL) if ra else max(pause, _MIN_INTERVAL)
                except ValueError:
                    pause = max(pause, _MIN_INTERVAL)
                print(f"[gdelt] quota temporaire — attente {pause:.0f}s (tentative {tentative + 1}/{retries})")
            time.sleep(max(pause, _MIN_INTERVAL))
            wait *= 2
        except Exception as exc:
            if tentative >= retries:
                print(f"[gdelt] erreur {exc}")
                return []
            time.sleep(wait)
            wait *= 1.5
    return []
