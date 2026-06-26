"""Provider local_sitemap (Phase 6.3).

Couche de découverte web sans clé : interroge les sitemaps/feeds des domaines
de presse régionale configurés, filtre les URLs/titres par les mots-clés de la
requête, et renvoie des articles normalisés.

Coûteux (multi-fetch HTTP) -> DÉSACTIVÉ par défaut (LOCAL_SITEMAP_ENABLED=0)
pour ne pas alourdir le run quotidien. Sécurisé par : timeout court, cache par
(domaine, path) entre appels, plafond de domaines interrogés par requête.

Variables :
    LOCAL_SITEMAP_ENABLED          (def. 0 — désactivé pour le quotidien)
    LOCAL_SITEMAP_DOMAINS          (def. liste presse régionale)
    LOCAL_SITEMAP_MAX_URLS_PER_DOMAIN (def. 200)
    LOCAL_SITEMAP_TIMEOUT          (def. 5 s)
    LOCAL_SITEMAP_MAX_DOMAINS      (def. 2 domaines par requête)
"""
from __future__ import annotations

import os
import re
import unicodedata
import xml.etree.ElementTree as ET

from backend.search_providers.types import normalize_result

_SOURCE = "Sitemap local"
_PATHS = ["/sitemap.xml", "/rss.xml", "/feed", "/sitemap_index.xml"]

_DEFAULT_DOMAINS = [
    "ici.fr", "actu.fr", "info-chalon.com", "dna.fr", "estrepublicain.fr",
]

# Cache process-wide des entrées parsées par (domaine, path) : évite de
# re-télécharger le même sitemap/flux à chaque requête d'un même run.
# Valeur = liste d'entrées {url, titre, date} (éventuellement []).
_ENTRIES_CACHE: dict[str, list[dict]] = {}


def clear_cache() -> None:
    """Vide le cache de sitemaps (utile en tests et entre deux runs)."""
    _ENTRIES_CACHE.clear()

_STOPWORDS = {
    "de", "la", "le", "les", "du", "des", "un", "une", "et", "au", "aux",
    "en", "dans", "son", "sa", "ses", "cette", "agence", "site", "https",
    "http", "www", "com", "fr",
}

# Seuil de pertinence : fraction des tokens de la requête présents dans
# l'URL/le titre pour retenir un résultat.
_MATCH_RATIO = 0.6


def _normalise(texte: str) -> str:
    sans = "".join(
        c for c in unicodedata.normalize("NFD", texte or "")
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", sans.lower()).strip()


def _query_tokens(query: str) -> list[str]:
    # Retire les opérateurs site:domaine et les guillemets.
    q = re.sub(r"site:\S+", " ", query or "")
    tokens = [t for t in _normalise(q).split() if len(t) >= 3 and t not in _STOPWORDS]
    return tokens


def _site_domains(query: str) -> list[str]:
    domains: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"\bsite:([^\s\"']+)", query or "", flags=re.IGNORECASE):
        domain = raw.strip().strip("()[]{}.,;")
        if domain.startswith("*."):
            domain = domain[2:]
        if domain and domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def _pertinent(tokens: list[str], texte: str) -> bool:
    if not tokens:
        return False
    cible = _normalise(texte)
    presents = sum(1 for t in tokens if t in cible)
    return presents / len(tokens) >= _MATCH_RATIO


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_xml(xml_text: str) -> list[dict]:
    """Retourne une liste de {url, titre, date} depuis un sitemap ou un flux RSS."""
    root = ET.fromstring(xml_text)
    items = [e for e in root.iter() if _local(e.tag) == "item"]
    if items:
        out = []
        for item in items:
            url = title = date = None
            for child in item:
                name = _local(child.tag)
                if name == "link":
                    url = (child.text or "").strip()
                elif name == "title":
                    title = (child.text or "").strip()
                elif name in ("pubdate", "lastmod", "date", "updated"):
                    date = (child.text or "").strip()
            if url:
                out.append({"url": url, "titre": title or "", "date": date})
        return out
    # Sinon : sitemap (urlset / sitemapindex) -> on collecte les <loc>.
    out = []
    for e in root.iter():
        if _local(e.tag) == "loc" and (e.text or "").strip():
            out.append({"url": e.text.strip(), "titre": "", "date": None})
    return out


def _fetch_entries(domain: str, path: str, fetch) -> list[dict]:
    """Récupère et parse un sitemap/flux, avec cache par (domaine, path)."""
    cle = f"{domain}{path}"
    if cle in _ENTRIES_CACHE:
        return _ENTRIES_CACHE[cle]
    url = f"https://{domain}{path}"
    try:
        entries = _parse_xml(fetch(url))
    except Exception:
        entries = []
    _ENTRIES_CACHE[cle] = entries
    return entries


def search(query: str, since: str | None = None, limit: int = 10, fetch=None) -> list[dict]:
    # Désactivé par défaut (0) : provider coûteux non exécuté dans le quotidien.
    if os.environ.get("LOCAL_SITEMAP_ENABLED", "0") == "0":
        return []
    domains_env = os.environ.get("LOCAL_SITEMAP_DOMAINS", "").strip()
    domains = [d.strip() for d in domains_env.split(",") if d.strip()] or _DEFAULT_DOMAINS
    site_domains = _site_domains(query)
    if site_domains:
        domains = site_domains + [d for d in domains if d not in site_domains]
    # Plafond de domaines interrogés par requête (best-effort, anti-explosion).
    max_domains = int(os.environ.get("LOCAL_SITEMAP_MAX_DOMAINS", "2"))
    domains = domains[:max(1, max_domains)]
    max_per_domain = int(os.environ.get("LOCAL_SITEMAP_MAX_URLS_PER_DOMAIN", "200"))
    tokens = _query_tokens(query)
    fetch = fetch or _default_fetch

    seen: set[str] = set()
    out: list[dict] = []
    for domain in domains:
        kept = 0
        for path in _PATHS:
            entries = _fetch_entries(domain, path, fetch)
            if not entries:
                continue
            for entry in entries[:max_per_domain]:
                u = entry.get("url") or ""
                if not u or u in seen:
                    continue
                if not _pertinent(tokens, f"{u} {entry.get('titre','')}"):
                    continue
                seen.add(u)
                out.append(normalize_result(
                    {"title": entry.get("titre"), "url": u, "date": entry.get("date")},
                    _SOURCE,
                ))
                kept += 1
                if kept >= max_per_domain or len(out) >= limit:
                    break
            if len(out) >= limit:
                break
        if len(out) >= limit:
            break
    return out


def _default_fetch(url: str) -> str:
    import requests

    timeout = int(os.environ.get("LOCAL_SITEMAP_TIMEOUT", "5"))
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "veille-presse/1.0"})
    resp.raise_for_status()
    return resp.text
