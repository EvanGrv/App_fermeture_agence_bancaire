from datetime import date
import os
import time
from typing import Literal, Optional
from pydantic import BaseModel, Field
import config
from backend.dedup import closure_id, normalise_cle

_INSTRUCTIONS = (
    "Tu analyses un article de presse français. Détermine s'il annonce la "
    "FERMETURE ou la FUSION/REGROUPEMENT d'une agence bancaire physique en France. "
    "Si oui, renvoie les informations structurées UNIQUEMENT si l'article nomme une "
    "commune précise d'agence concernée. Si l'article parle d'un plan national, d'une "
    "grève, de suppressions de postes, d'un volume global d'agences, d'une région ou "
    "d'un département sans lister au moins une commune d'agence, mets concerne_banque=false. "
    "N'invente jamais de commune: n'utilise pas 'inconnu', une région, un département, "
    "une caisse régionale ou un territoire comme commune. Si l'article ne concerne pas "
    "une fermeture/fusion d'agence bancaire nominative, mets concerne_banque=false. "
    "IMPORTANT : on ne s'intéresse QU'AUX fermetures à VENIR (annoncées, pas encore "
    "effectives à la date du jour indiquée). Classe statut_temporel : 'a_venir' si la "
    "fermeture n'a pas encore eu lieu à la date du jour, 'deja_fermee' si elle est déjà "
    "effective (l'agence a déjà fermé), 'inconnu' si l'article ne permet pas de trancher. "
    "fiabilite: 1 (rumeur vague) à 5 (annonce officielle confirmée). "
    "date_fermeture: date prévue ISO YYYY-MM-DD si connue. "
    "citation: la phrase exacte de l'article qui justifie la fermeture/fusion."
)
_RETRY_STATUS_CODES = {429, 500, 504, 529}
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE_SECONDS = 2.0
_DEFAULT_RETRY_MAX_SECONDS = 30.0

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
    "credit cooperatif": "Crédit Coopératif",
}
for _groupe, _variantes in getattr(config, "MARQUES_REGIONALES", {}).items():
    for _variante in _variantes:
        _CANON[normalise_cle(_variante)] = _groupe


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


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is not None:
        return status
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _parse_avec_retries(client, *, model: str, messages: list[dict], sleep_fn=time.sleep):
    max_retries = max(0, _int_env("ANTHROPIC_MAX_RETRIES", _DEFAULT_MAX_RETRIES))
    base = max(0.0, _float_env("ANTHROPIC_RETRY_BASE_SECONDS", _DEFAULT_RETRY_BASE_SECONDS))
    plafond = max(base, _float_env("ANTHROPIC_RETRY_MAX_SECONDS", _DEFAULT_RETRY_MAX_SECONDS))
    for tentative in range(max_retries + 1):
        try:
            return client.messages.parse(
                model=model,
                max_tokens=1024,
                messages=messages,
                output_format=Extraction,
            )
        except Exception as exc:
            status = _status_code(exc)
            if status not in _RETRY_STATUS_CODES or tentative >= max_retries:
                raise
            attente = min(plafond, base * (2 ** tentative))
            print(f"[extractor] Anthropic {status} — nouvelle tentative dans {attente:g}s")
            sleep_fn(attente)


def extract(article: dict, client, model: str = config.ANTHROPIC_MODEL,
            aujourdhui: Optional[str] = None) -> Optional[dict]:
    aujourdhui = aujourdhui or date.today().isoformat()
    try:
        response = _parse_avec_retries(
            client,
            model=model,
            messages=build_messages(article, aujourdhui),
        )
        data: Extraction = response.parsed_output
    except Exception as exc:
        if (
            _status_code(exc) in _RETRY_STATUS_CODES
            and os.environ.get("OPENAI_API_KEY")
            and os.environ.get("OPENAI_FALLBACK_ENABLED", "1") != "0"
        ):
            from backend.openai_fallback import extract_openai
            data = extract_openai(article, aujourdhui)
        else:
            raise
    if data is None or not data.concerne_banque:
        return None
    # On ne garde que les fermetures à venir : on écarte celles déjà effectives.
    if data.statut_temporel == "deja_fermee":
        return None
    if _est_passee(data.date_fermeture, aujourdhui):
        return None
    if data.statut_temporel == "inconnu" and not data.date_fermeture:
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
