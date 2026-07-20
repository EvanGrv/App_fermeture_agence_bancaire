import hashlib
import re

import config
from backend.dedup import normalise_cle
from backend.extractor import normalise_banque
from backend import prefilter, store


def vigilance_id(article: dict) -> str:
    cle = article.get("url") or f"{article.get('titre','')}|{article.get('date','')}"
    return hashlib.sha256(cle.encode("utf-8")).hexdigest()[:16]


def _texte(article: dict) -> str:
    return f"{article.get('titre','')} {article.get('texte','')}"


def _banque(article: dict) -> str | None:
    # Les descriptions Google News contiennent parfois les cartes HTML
    # d'articles voisins et donc des noms de banques sans rapport. Un titre qui
    # annonce explicitement la fermeture d'un bureau de poste est prioritaire.
    titre_article = {"titre": article.get("titre") or "", "texte": ""}
    if prefilter.is_postal_closure_candidate(titre_article):
        return "La Banque Postale"
    texte_norm = normalise_cle(_texte(article))
    candidats = list(config.ENSEIGNES)
    for variantes in getattr(config, "MARQUES_REGIONALES", {}).values():
        candidats.extend(variantes)
    for nom in sorted(candidats, key=len, reverse=True):
        if normalise_cle(nom) in texte_norm:
            banque = normalise_banque(nom)
            if normalise_cle(banque) in getattr(config, "EXCLURE_BANQUES", []):
                return None
            return banque
    if prefilter.is_postal_closure_candidate(article):
        return "La Banque Postale"
    return None


def _extrait(article: dict, max_len: int = 500) -> str:
    texte = re.sub(r"\s+", " ", article.get("texte") or article.get("titre") or "").strip()
    return texte[:max_len]


def _score(article: dict) -> int:
    texte_norm = normalise_cle(_texte(article))
    score = 1
    if _banque(article):
        score += 1
    if article.get("source") == "Légifrance":
        score += 1
    termes = sum(1 for terme in config.TERMES_FERMETURE if normalise_cle(terme) in texte_norm)
    if termes >= 2:
        score += 1
    if "pse" in texte_norm or "restructuration" in texte_norm:
        score += 1
    return min(score, 5)


def depuis_article(article: dict, raison: str = "signal faible") -> dict | None:
    if not prefilter.is_relevant(article):
        return None
    return {
        "id": vigilance_id(article),
        "banque": _banque(article),
        "departement": article.get("departement"),
        "titre": article.get("titre") or "",
        "extrait": _extrait(article),
        "url": article.get("url") or "",
        "source": article.get("source") or "",
        "date": article.get("date") or "",
        "score": _score(article),
        "raison": raison,
    }


def ingest_articles(conn, articles: list[dict], raison: str = "signal faible") -> int:
    n = 0
    for article in articles:
        vigilance = depuis_article(article, raison=raison)
        if vigilance is None:
            continue
        store.upsert_vigilance(conn, vigilance)
        n += 1
    return n


def reclassify_postal_vigilances(conn) -> int:
    """Répare les anciennes vigilances postales polluées par leur extrait RSS.

    Les revues associées sont supprimées pour permettre une nouvelle analyse
    immédiate avec la bonne enseigne.
    """
    rows = conn.execute("SELECT id, titre, banque FROM vigilances").fetchall()
    ids = [
        vid for vid, titre, banque in rows
        if prefilter.is_postal_closure_candidate({"titre": titre or "", "texte": ""})
        and banque != "La Banque Postale"
    ]
    if not ids:
        return 0
    conn.executemany(
        "UPDATE vigilances SET banque='La Banque Postale' WHERE id=? AND "
        "COALESCE(banque, '') != 'La Banque Postale'",
        [(vid,) for vid in ids],
    )
    conn.executemany("DELETE FROM vigilance_reviews WHERE id=?", [(vid,) for vid in ids])
    conn.commit()
    return len(ids)
