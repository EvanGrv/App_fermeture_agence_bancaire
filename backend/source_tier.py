"""Source quality tier A→E derived from URL domain.

Scale:
  A — communiqué officiel (banque / institution / gouv)
  B — PQR identifiée (presse quotidienne régionale)
  C — bonne source complémentaire (France 3 / France Bleu / actu.fr / ici.fr)
  D — autre presse / défaut / URL vide ou non parseable
  E — réseaux sociaux, annuaires, avis
"""
from urllib.parse import urlparse

# ── Tier A: official banks and government ─────────────────────────────────────
A_DOMAINS: frozenset[str] = frozenset({
    "credit-agricole.fr",
    "sg.fr",
    "labanquepostale.fr",
    "caisse-epargne.fr",
    "banquepopulaire.fr",
    "creditmutuel.fr",
    "cic.fr",
    "lcl.fr",
    "bnpparibas.fr",
    "bnpparibas.com",
    "boursobank.com",
    "hsbc.fr",
    "ing.fr",
    "fortuneo.fr",
    "monabanq.com",
    "hellobank.fr",
    "caissedesdepots.fr",
    "mairie.fr",
})

# ── Tier B: PQR (presse quotidienne régionale) ────────────────────────────────
B_DOMAINS: frozenset[str] = frozenset({
    "ouest-france.fr",
    "sudouest.fr",
    "ladepeche.fr",
    "lavoixdunord.fr",
    "lanouvellerepublique.fr",
    "ledauphine.com",
    "estrepublicain.fr",
    "republicain-lorrain.fr",
    "paris-normandie.fr",
    "lamontagne.fr",
    "leprogres.fr",
    "letelegramme.fr",
    "nicematin.com",
    "midilibre.fr",
    "lindependant.fr",
    "leparisien.fr",
    "lyoncapitale.fr",
    "lyonmag.com",
    "lunion.fr",
    "lejsl.com",
    "courrier-picard.fr",
    "voixdunord.fr",
    "lalsace.fr",
    "dna.fr",
    "bienpublic.com",
    "lepays.fr",
    "lopinion.fr",
    "latribune.fr",
    "lesechos.fr",
    "lefigaro.fr",
    "lemonde.fr",
    "liberation.fr",
})

# ── Tier C: good complementary sources ────────────────────────────────────────
C_DOMAINS: frozenset[str] = frozenset({
    "francetvinfo.fr",
    "france3-regions.francetvinfo.fr",
    "france3.fr",
    "ici.fr",
    "francebleu.fr",
    "actu.fr",
    "bfmtv.com",
    "rfi.fr",
    "rtl.fr",
    "europe1.fr",
    "20minutes.fr",
})

# ── Tier E: social networks, directories, review sites ───────────────────────
E_DOMAINS: frozenset[str] = frozenset({
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "pagesjaunes.fr",
    "tiktok.com",
    "snapchat.com",
    "reddit.com",
    "tripadvisor.fr",
    "tripadvisor.com",
    "yelp.fr",
    "yelp.com",
    "avis-verifies.com",
    "trustpilot.com",
})


def _matches(host: str, domain_set: frozenset[str]) -> bool:
    """Return True if host equals a domain in the set or is a subdomain of it."""
    if host in domain_set:
        return True
    for domain in domain_set:
        if host.endswith("." + domain):
            return True
    return False


def tier(url: str) -> str:
    """Return quality tier 'A'–'E' for the given URL's domain.

    Precedence: A > B > C > E > D
    Empty/unparseable URL → 'D' (unknown press, not E).
    """
    if not url:
        return "D"

    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
    except Exception:
        return "D"

    host = host.lower().lstrip(".")
    # strip leading www.
    if host.startswith("www."):
        host = host[4:]

    if not host:
        return "D"

    # Tier A: specific bank domains
    if _matches(host, A_DOMAINS):
        return "A"

    # Tier A: any *.gouv.fr or anything containing 'mairie' in the host
    if host.endswith(".gouv.fr") or host == "gouv.fr":
        return "A"
    if "mairie" in host:
        return "A"

    # Tier A: bnpparibas in host (covers bnpparibas.net, etc.)
    if "bnpparibas" in host:
        return "A"

    # Tier B
    if _matches(host, B_DOMAINS):
        return "B"

    # Tier C
    if _matches(host, C_DOMAINS):
        return "C"

    # Tier E
    if _matches(host, E_DOMAINS):
        return "E"
    # Google maps/reviews → E; news.google.com → D (aggregator)
    # Only classify as E when the keyword appears in the URL PATH (not query),
    # or the host is maps.google.*
    if host.startswith("maps.google.") or (
        "google." in host
        and host != "news.google.com"
        and any(
            k in urlparse(url).path.lower()
            for k in ("maps", "avis", "reviews", "business")
        )
    ):
        return "E"

    # Tier D: default (unknown press / aggregator)
    return "D"
