"""Vocabulaire commun aux agrégateurs de presse complémentaires."""

BANK_TERMS = (
    '"agence bancaire"',
    '"agences bancaires"',
    '"La Banque Postale"',
    '"bureau de poste"',
    '"bureaux de poste"',
    '"Crédit Agricole"',
    'BNP',
    'SG',
    '"Société Générale"',
    '"Banque Populaire"',
    '"Caisse d\'Épargne"',
    '"Crédit Mutuel"',
    'CIC',
    'LCL',
    'CCF',
)

CLOSURE_TERMS = (
    'fermeture',
    'fermetures',
    'fermera',
    '"va fermer"',
    '"cessera son activité"',
    'suppression',
    'fusion',
    'regroupement',
    'transfert',
    'transformation',
)


def mediacloud_query() -> str:
    banks = " OR ".join(BANK_TERMS)
    closures = " OR ".join(CLOSURE_TERMS)
    return f"language:fr AND ({banks}) AND ({closures})"


def event_registry_query() -> dict:
    def alternatives(values: tuple[str, ...]) -> dict:
        return {
            "$or": [
                {"keyword": value.strip('"')}
                for value in values
            ]
        }

    return {
        "$query": {
            "$and": [
                alternatives(BANK_TERMS),
                alternatives(CLOSURE_TERMS),
            ]
        }
    }


# Le filtre CDX travaille sur les URLs, pas sur le corps des pages. Deux filtres
# sont combinés par le serveur afin d'éviter les pages parlant d'une agence sans
# annoncer de fermeture.
COMMON_CRAWL_CLOSURE_URL_FILTER = (
    r".*(ferm|cess|supprim|fusion|regroup|transf|convert|relais|remplac).*"
)
COMMON_CRAWL_BANK_URL_FILTER = (
    r".*(agence|banque|bancaire|poste|postal|bureau|reseau).*"
)
