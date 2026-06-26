import urllib.parse
from datetime import date, timedelta
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
    "banque cesse son activité agence",
    "agence bancaire transférée",
    "réorganisation réseau bancaire agence",
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
        # Domaines observés dans la base de référence élargie (Excel mairies/PQR).
        "dna.fr",
        "info-chalon.com",
        "deltafm.fr",
        "europesays.com",
        "bienpublic.com",
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

# Requêtes à volume élevé qui saturent le plafond ~100 résultats/flux.
# Elles seront découpées mois par mois dans collect() pour récupérer la queue.
# = toutes les thématiques génériques + les 3 grandes banques nationales.
_BIG_BANKS_NATIONAL = [
    q for q in _PAR_ENSEIGNE
    if any(q.startswith(enseigne) for enseigne in ("Crédit Agricole", "Société Générale", "BNP"))
]
_DENSE: set[str] = set(_THEMATIQUES) | set(_BIG_BANKS_NATIONAL)


def _parse_when_to_start(when: str, today: date) -> "date | None":
    """Parse a Google News ``when:`` string and return the start date.

    Supported units: ``d`` (days), ``y`` (years = 365 days), ``h`` (hours → same day).
    Returns ``None`` if *when* is empty or unparseable.

    Example::

        _parse_when_to_start("30d", date(2026, 6, 25))  # → date(2026, 5, 26)
        _parse_when_to_start("1y",  date(2026, 6, 25))  # → date(2025, 6, 25)
        _parse_when_to_start("24h", date(2026, 6, 25))  # → date(2026, 6, 25)
    """
    if not when:
        return None
    unit = when[-1].lower()
    try:
        n = int(when[:-1])
    except (ValueError, IndexError):
        return None
    if unit == "d":
        return today - timedelta(days=n)
    if unit == "y":
        return today - timedelta(days=n * 365)
    if unit == "h":
        return today  # sub-day granularity: treat as same day
    return None  # unsupported unit (e.g. 'm' = minutes in Google News)


def _month_ranges(start: date, end: date) -> list[tuple[str, str]]:
    """Produce month-aligned date buckets covering [start, end] inclusive.

    Each bucket is ``(after_str, before_str)`` in ISO format where *after* is
    the inclusive start and *before* is the exclusive upper bound (one day past
    the last day in the bucket).  Buckets tile the whole span with no gaps.

    Example::

        _month_ranges(date(2025, 11, 15), date(2026, 2, 10))
        # → [("2025-11-15", "2025-12-01"),
        #    ("2025-12-01", "2026-01-01"),
        #    ("2026-01-01", "2026-02-01"),
        #    ("2026-02-01", "2026-02-11")]
    """
    buckets: list[tuple[str, str]] = []
    cursor = start
    end_exclusive = end + timedelta(days=1)  # last bucket's before

    while cursor < end_exclusive:
        # Compute next month boundary
        if cursor.month == 12:
            next_month_start = date(cursor.year + 1, 1, 1)
        else:
            next_month_start = date(cursor.year, cursor.month + 1, 1)

        bucket_end = min(next_month_start, end_exclusive)
        buckets.append((cursor.isoformat(), bucket_end.isoformat()))
        cursor = bucket_end

    return buckets


def _feed_url(query: str, after: str | None = None, before: str | None = None) -> str:
    """Build a Google News RSS search URL for *query*.

    If *after* and *before* are provided, use ``after:YYYY-MM-DD before:YYYY-MM-DD``
    date operators instead of the global ``when:`` window.
    """
    if after and before:
        q = urllib.parse.quote(f"{query} after:{after} before:{before}")
    else:
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
    today = date.today()
    when = getattr(config, "GOOGLE_NEWS_WHEN", "")
    start = _parse_when_to_start(when, today)

    for query in queries:
        # Dense queries with a parseable window are sliced month-by-month.
        if query in _DENSE and start is not None:
            buckets = _month_ranges(start, today)
            urls_to_fetch = [
                _feed_url(query, after=after, before=before)
                for after, before in buckets
            ]
        else:
            urls_to_fetch = [_feed_url(query)]

        for url in urls_to_fetch:
            try:
                xml = fetch(url)
            except Exception as exc:  # une source en panne ne casse pas le run
                print(f"[google_news] requête '{query}': erreur {exc}")
                continue
            for art in parse_feed(xml):
                art_url = art.get("url") or ""
                if art_url and art_url in vus:
                    continue
                if art_url:
                    vus.add(art_url)
                resultats.append(art)
    return resultats
