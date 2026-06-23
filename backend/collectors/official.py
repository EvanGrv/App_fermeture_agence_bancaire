# IMPORTANT — limite vérifiée : le registre REGAFI (ACPR/Banque de France) est
# au niveau de l'ÉTABLISSEMENT agréé (entité + siège), PAS au niveau des agences
# individuelles. Il ne contient ni adresse d'agence, ni date de fermeture
# d'agence. REGAFI ne peut donc PAS fournir « les agences qui ferment ».
# (API: developer.regafi.banque-france.fr — données entités, inscription requise.)
#
# Ce collecteur reste un ingesteur GÉNÉRIQUE de CSV structuré (colonnes
# denomination, commune, code_postal, statut) : utile si tu obtiens un jour une
# liste d'agences au bon niveau (source interne, dataset tiers). Dépose-la dans
# data/cache/regafi.csv. Les fermetures d'agences restent sinon couvertes par la
# presse (Google News / GDELT).
import csv
import io
import config

_TERMES_RETRAIT = ("radié", "radie", "cessation")


def parse_csv(contenu: str) -> list[dict]:
    lecteur = csv.DictReader(io.StringIO(contenu))
    articles = []
    for ligne in lecteur:
        statut = (ligne.get("statut") or "").lower()
        if not any(t in statut for t in _TERMES_RETRAIT):
            continue
        commune = (ligne.get("commune") or "").strip()
        denomination = (ligne.get("denomination") or "").strip()
        cp = (ligne.get("code_postal") or "").strip()
        departement = cp[:2] if cp else None
        articles.append({
            "titre": f"{denomination} — {ligne.get('statut')}",
            "texte": f"{denomination} à {commune} ({cp}) : {ligne.get('statut')}.",
            "url": f"acpr://{denomination}/{commune}",
            "date": "",
            "source": "ACPR",
            "departement": departement,
            "commune": commune,
        })
    return articles


def _default_loader() -> str | None:
    chemin = config.CACHE_DIR / "regafi.csv"
    if chemin.exists():
        return chemin.read_text(encoding="utf-8")
    print("[official] data/cache/regafi.csv absent — collecteur officiel ignoré")
    return None


def collect(loader=_default_loader) -> list[dict]:
    contenu = loader()
    if not contenu:
        return []
    return parse_csv(contenu)
