import os

CREDENTIALS = {
    "FACTIVA_API_KEY": "Factiva",
    "LEXISNEXIS_API_KEY": "LexisNexis",
    "TAGADAY_API_KEY": "Tagaday",
}


def _actifs() -> list[str]:
    return [label for env, label in CREDENTIALS.items() if os.environ.get(env)]


def collect(fetch=None) -> list[dict]:
    """Scaffold presse professionnelle payante.

    Les adaptateurs réels ne sont volontairement pas implémentés ici. Sans clé,
    ou même avec clé, ce module ne publie aucune donnée et ne fait aucun appel.
    """
    actifs = _actifs()
    if not actifs:
        print("[presse_pro] aucun credential, collecteur désactivé")
        return []
    print(f"[presse_pro] adaptateurs non implémentés: {', '.join(actifs)}")
    return []
