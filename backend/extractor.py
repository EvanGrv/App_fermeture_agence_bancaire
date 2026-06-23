from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field
import config
from backend.dedup import closure_id, normalise_cle

_INSTRUCTIONS = (
    "Tu analyses un article de presse français. Détermine s'il annonce la "
    "FERMETURE ou la FUSION/REGROUPEMENT d'une agence bancaire physique en France. "
    "Si oui, renvoie les informations structurées. Si l'article ne concerne pas "
    "une fermeture/fusion d'agence bancaire, mets concerne_banque=false. "
    "IMPORTANT : on ne s'intéresse QU'AUX fermetures à VENIR (annoncées, pas encore "
    "effectives à la date du jour indiquée). Classe statut_temporel : 'a_venir' si la "
    "fermeture n'a pas encore eu lieu à la date du jour, 'deja_fermee' si elle est déjà "
    "effective (l'agence a déjà fermé), 'inconnu' si l'article ne permet pas de trancher. "
    "fiabilite: 1 (rumeur vague) à 5 (annonce officielle confirmée). "
    "date_fermeture: date prévue ISO YYYY-MM-DD si connue. "
    "citation: la phrase exacte de l'article qui justifie la fermeture/fusion."
)

# Formes canoniques des principales enseignes (clé = forme normalisée).
_CANON = {
    "credit agricole": "Crédit Agricole",
    "credit mutuel": "Crédit Mutuel",
    "credit mutuel alliance federale": "Crédit Mutuel",
    "banque populaire": "Banque Populaire",
    "caisse d'epargne": "Caisse d'Épargne",
    "societe generale": "Société Générale",
    "la banque postale": "La Banque Postale",
    "banque postale": "La Banque Postale",
    "bnp paribas": "BNP Paribas",
    "bnp": "BNP Paribas",
    "lcl": "LCL",
    "cic": "CIC",
    "credit du nord": "Crédit du Nord",
    "hsbc": "HSBC",
}


def normalise_banque(nom: str) -> str:
    canon = _CANON.get(normalise_cle(nom or ""))
    return canon if canon else (nom or "").strip()


class Extraction(BaseModel):
    concerne_banque: bool = Field(description="True si fermeture/fusion d'agence bancaire")
    banque: str
    commune: str
    departement: Optional[str] = None
    type: Literal["fermeture", "fusion"]
    statut_temporel: Literal["a_venir", "deja_fermee", "inconnu"] = "inconnu"
    date_fermeture: Optional[str] = Field(default=None, description="ISO YYYY-MM-DD si connue")
    statut: Literal["confirmé", "projet", "rumeur"]
    fiabilite: int = Field(ge=0, le=5)
    citation: str


def build_messages(article: dict, aujourdhui: Optional[str] = None) -> list[dict]:
    aujourdhui = aujourdhui or date.today().isoformat()
    corps = (
        f"{_INSTRUCTIONS}\n\n"
        f"DATE DU JOUR: {aujourdhui}\n"
        f"TITRE: {article.get('titre','')}\n"
        f"TEXTE: {article.get('texte','')}\n"
        f"DÉPARTEMENT (indice): {article.get('departement')}"
    )
    return [{"role": "user", "content": corps}]


def _est_passee(date_fermeture: Optional[str], aujourdhui: str) -> bool:
    """True si la date de fermeture ISO est strictement antérieure à aujourd'hui."""
    if not date_fermeture:
        return False
    try:
        return date.fromisoformat(date_fermeture[:10]) < date.fromisoformat(aujourdhui)
    except ValueError:
        return False


def extract(article: dict, client, model: str = config.ANTHROPIC_MODEL,
            aujourdhui: Optional[str] = None) -> Optional[dict]:
    aujourdhui = aujourdhui or date.today().isoformat()
    response = client.messages.parse(
        model=model,
        max_tokens=1024,
        messages=build_messages(article, aujourdhui),
        output_format=Extraction,
    )
    data: Extraction = response.parsed_output
    if data is None or not data.concerne_banque:
        return None
    # On ne garde que les fermetures à venir : on écarte celles déjà effectives.
    if data.statut_temporel == "deja_fermee":
        return None
    if _est_passee(data.date_fermeture, aujourdhui):
        return None
    banque = normalise_banque(data.banque)
    # Enseignes exclues du suivi (ex. La Banque Postale).
    if normalise_cle(banque) in getattr(config, "EXCLURE_BANQUES", []):
        return None
    return {
        "id": closure_id(banque, data.commune, data.type),
        "banque": banque,
        "commune": data.commune,
        "code_insee": None,
        "departement": data.departement or article.get("departement"),
        "type": data.type,
        "date_annonce": article.get("date") or None,
        "date_fermeture": data.date_fermeture,
        "statut": data.statut,
        "fiabilite": data.fiabilite,
        "lat": None,
        "lon": None,
        "citation": data.citation,
    }
