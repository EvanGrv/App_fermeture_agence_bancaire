from typing import Literal, Optional
from pydantic import BaseModel, Field
import config
from backend.dedup import closure_id

_INSTRUCTIONS = (
    "Tu analyses un article de presse français. Détermine s'il annonce la "
    "FERMETURE ou la FUSION/REGROUPEMENT d'une agence bancaire physique en France. "
    "Si oui, renvoie les informations structurées. Si l'article ne concerne pas "
    "une fermeture/fusion d'agence bancaire, mets concerne_banque=false. "
    "fiabilite: 1 (rumeur vague) à 5 (annonce officielle confirmée). "
    "citation: la phrase exacte de l'article qui justifie la fermeture/fusion."
)


class Extraction(BaseModel):
    concerne_banque: bool = Field(description="True si fermeture/fusion d'agence bancaire")
    banque: str
    commune: str
    departement: Optional[str] = None
    type: Literal["fermeture", "fusion"]
    date_fermeture: Optional[str] = Field(default=None, description="ISO YYYY-MM-DD si connue")
    statut: Literal["confirmé", "projet", "rumeur"]
    fiabilite: int = Field(ge=1, le=5)
    citation: str


def build_messages(article: dict) -> list[dict]:
    corps = (
        f"{_INSTRUCTIONS}\n\n"
        f"TITRE: {article.get('titre','')}\n"
        f"TEXTE: {article.get('texte','')}\n"
        f"DÉPARTEMENT (indice): {article.get('departement')}"
    )
    return [{"role": "user", "content": corps}]


def extract(article: dict, client, model: str = config.ANTHROPIC_MODEL) -> Optional[dict]:
    response = client.messages.parse(
        model=model,
        max_tokens=1024,
        messages=build_messages(article),
        output_format=Extraction,
    )
    data: Extraction = response.parsed_output
    if data is None or not data.concerne_banque:
        return None
    return {
        "id": closure_id(data.banque, data.commune, data.type),
        "banque": data.banque,
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
