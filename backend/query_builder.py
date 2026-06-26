"""Construction de requêtes ciblées pour les sources locales.

Génère, pour un couple (banque, commune), une liste de requêtes destinées aux
providers de recherche (Brave/Bing) ou aux flux locaux : formulations typiques
de la presse régionale + requêtes `site:` sur les domaines prioritaires.

Les chaînes banque/commune sont reprises telles quelles (accents et variantes
régionales conservés) — la normalisation est l'affaire des étapes en aval.
"""
from __future__ import annotations

from itertools import zip_longest

# Formulations fréquentes dans la presse locale / les comptes-rendus de mairie.
FORMULATIONS = [
    "fermeture agence",
    "fermera définitivement",
    "ferme ses portes",
    "cessera son activité",
    "cessation d'activité",
    "perd sa banque",
    "la banque ferme dans cette commune",
    "sociétaires se mobilisent",
    "conseil municipal fermeture agence",
    "mairie fermeture agence bancaire",
    "maintien du distributeur",
    "DAB maintenu",
]

# Requêtes de découverte quand la vigilance ne donne pas encore de commune
# validable : elles servent à retrouver un article plus complet ou un article
# source listant les communes concernées.
DISCOVERY_FORMULATIONS = [
    "fermeture agences",
    "agences vont fermer",
    "ferme ses agences",
    "fermetures d'agences",
    "liste des agences",
    "communes concernées",
    "conseil municipal fermeture agence",
]

# Domaines de presse/radio régionale prioritaires (cf. plan Phase 6.3).
DEFAULT_DOMAINS = [
    "ici.fr", "actu.fr", "ouest-france.fr", "lanouvellerepublique.fr",
    "estrepublicain.fr", "dna.fr", "info-chalon.com", "deltafm.fr",
    "lavoixdunord.fr", "sudouest.fr", "leprogres.fr", "ledauphine.com",
    "republicain-lorrain.fr", "paris-normandie.fr", "lepopulaire.fr",
    "lardennais.fr",
]


def build_queries(
    banque: str,
    commune: str,
    *,
    departement: str | None = None,
    domains: list[str] | None = None,
    max_queries: int = 8,
) -> list[str]:
    """Construit une liste de requêtes ciblées, dédupliquée et plafonnée.

    Retourne [] si la banque ou la commune manque.
    """
    banque = (banque or "").strip()
    commune = (commune or "").strip()
    if not banque or not commune:
        return []
    if domains is None:
        domains = DEFAULT_DOMAINS

    # Requêtes "plein texte" avec guillemets pour ancrer banque + commune.
    text_queries = [f'"{banque}" "{commune}" "{f}"' for f in FORMULATIONS]
    text_queries.append(f'"{commune}" "agence {banque}"')
    text_queries.append(f'mairie "{commune}" "{banque}" fermeture')
    # Requêtes site: par domaine local.
    site_queries = [f'site:{domain} "{banque}" "{commune}"' for domain in domains]

    # Entrelacer plein-texte et site: pour que les deux types apparaissent même
    # avec un petit budget de requêtes.
    candidates: list[str] = []
    for text_q, site_q in zip_longest(text_queries, site_queries):
        if text_q:
            candidates.append(text_q)
        if site_q:
            candidates.append(site_q)

    # Dédup en conservant l'ordre, puis plafonnement.
    seen: set[str] = set()
    out: list[str] = []
    for q in candidates:
        if q in seen:
            continue
        seen.add(q)
        out.append(q)
        if len(out) >= max_queries:
            break
    return out


def build_discovery_queries(
    banque: str,
    *,
    hint: str | None = None,
    domains: list[str] | None = None,
    max_queries: int = 8,
) -> list[str]:
    """Construit des requêtes quand la commune manque encore.

    `hint` est un fragment du titre/extrait (ex. "Haute-Loire", "Normandie",
    "21 agences") qui aide à retrouver l'article source sans inventer de
    commune.
    """
    banque = (banque or "").strip()
    hint = (hint or "").strip()
    if not banque:
        return []
    if domains is None:
        domains = DEFAULT_DOMAINS

    text_queries = [f'"{banque}" "{f}"' for f in DISCOVERY_FORMULATIONS]
    if hint:
        text_queries = [f'"{banque}" "{hint}" "{f}"' for f in DISCOVERY_FORMULATIONS[:4]] + text_queries

    site_queries = [f'site:{domain} "{banque}" "fermeture agence"' for domain in domains]
    if hint:
        site_queries = [
            f'site:{domain} "{banque}" "{hint}" "fermeture"'
            for domain in domains
        ] + site_queries

    candidates: list[str] = []
    for text_q, site_q in zip_longest(text_queries, site_queries):
        if text_q:
            candidates.append(text_q)
        if site_q:
            candidates.append(site_q)

    seen: set[str] = set()
    out: list[str] = []
    for q in candidates:
        if q in seen:
            continue
        seen.add(q)
        out.append(q)
        if len(out) >= max_queries:
            break
    return out
