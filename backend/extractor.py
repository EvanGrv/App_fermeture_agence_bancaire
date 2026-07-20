from datetime import date
import os
import re
import time
from typing import Literal, Optional
from pydantic import BaseModel, Field
import config
from backend.dedup import closure_id, normalise_cle

_INSTRUCTIONS = (
    "Tu analyses un article de presse français. Détermine s'il annonce ou rapporte "
    "la FERMETURE ou la FUSION/REGROUPEMENT d'une agence bancaire physique en France. "
    "Renvoie les informations structurées UNIQUEMENT si l'article nomme une commune "
    "précise d'agence concernée. Sinon concerne_banque=false. "
    "N'invente jamais de commune (pas de région, département, caisse régionale). "
    "On s'intéresse aux fermetures DÉJÀ EFFECTIVES comme À VENIR. Classe statut_temporel : "
    "'a_venir' si la fermeture n'a pas encore eu lieu à la date du jour, 'deja_fermee' si "
    "elle est déjà effective, 'inconnu' sinon. "
    "date_fermeture: date effective ISO YYYY-MM-DD. Si l'article ne donne qu'une PÉRIODE "
    "(ex. 'courant 2025', 'au printemps 2025', 'fin 2025'), renvoie une date approchée "
    "dans cette période et mets date_fermeture_approx=true. Si AUCUNE date ni période "
    "exploitable pour une fermeture déjà effective, laisse date_fermeture vide. "
    "EXCLURE (concerne_banque=false) : fermeture temporaire, travaux, simple suppression "
    "de distributeur (DAB), déménagement dans la MÊME commune, changement d'horaires. "
    "fiabilite: 1 (rumeur vague) à 5 (annonce officielle confirmée). "
    "citation: la phrase exacte qui justifie la fermeture/fusion. "
    "Cas La Banque Postale : un bureau de poste peut compter comme point bancaire "
    "uniquement si l'article mentionne explicitement La Banque Postale, des services "
    "financiers/bancaires, un conseiller bancaire, ou la perte d'un service bancaire. "
    "Si l'article annonce la fermeture permanente d'un BUREAU DE POSTE nommé dans "
    "une commune précise, traite-le comme candidat La Banque Postale même si le titre "
    "dit surtout 'La Poste' ; garde une fiabilité modérée (2-3) sauf preuve bancaire "
    "explicite. Ne retiens pas les agences postales communales/relais sauf mention "
    "bancaire explicite. "
    "Sinon, une simple fermeture postale est hors périmètre."
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
    # Toujours normalisé pour que les anciennes données soient regroupées à
    # l'affichage, même lorsque cette enseigne optionnelle n'est pas collectée.
    "credit municipal": "Crédit Municipal",
}

# Toute enseigne ajoutée à la configuration bénéficie automatiquement de la
# normalisation, sans devoir maintenir une seconde liste manuellement.
for _enseigne in config.ENSEIGNES:
    _cle_enseigne = normalise_cle(_enseigne)
    _CANON.setdefault(
        _cle_enseigne,
        "BNP Paribas" if _cle_enseigne == "bnp" else _enseigne,
    )
for _groupe, _variantes in getattr(config, "MARQUES_REGIONALES", {}).items():
    for _variante in _variantes:
        _CANON[normalise_cle(_variante)] = _groupe


def _cle_enseigne(nom: str) -> str:
    """Clé tolérante aux apostrophes, tirets et ponctuation de marque."""
    return re.sub(r"[^a-z0-9]+", " ", normalise_cle(nom or "")).strip()


# Les préfixes sont construits depuis les enseignes, pas depuis les caisses
# régionales connues. Une nouvelle variante telle que "Enseigne Région X" est
# ainsi regroupée sans modification de code ni ajout dans MARQUES_REGIONALES.
_PREFIXES_CANONIQUES = sorted(
    {
        (_cle_enseigne(canon), canon)
        for canon in _CANON.values()
        if _cle_enseigne(canon)
    },
    key=lambda item: len(item[0]),
    reverse=True,
)


def normalise_banque(nom: str) -> str:
    cle = normalise_cle(nom or "")
    canon = _CANON.get(cle)
    if canon is None:
        cle_souple = _cle_enseigne(nom)
        canon = next(
            (
                enseigne
                for prefixe, enseigne in _PREFIXES_CANONIQUES
                if cle_souple == prefixe or cle_souple.startswith(f"{prefixe} ")
            ),
            None,
        )
    return canon if canon else (nom or "").strip()


KNOWN_BANKS: set[str] = {normalise_banque(enseigne) for enseigne in config.ENSEIGNES}


def banque_connue(banque: str) -> bool:
    return banque in KNOWN_BANKS


class Extraction(BaseModel):
    concerne_banque: bool = Field(description="True si fermeture/fusion d'agence bancaire")
    banque: str
    commune: str
    departement: Optional[str] = None
    type: Literal["fermeture", "fusion"]
    statut_temporel: Literal["a_venir", "deja_fermee", "inconnu"] = "inconnu"
    date_fermeture: Optional[str] = Field(default=None, description="ISO YYYY-MM-DD si connue")
    date_fermeture_approx: bool = Field(
        default=False,
        description="True si la date est approximée depuis une période (ex. 'courant 2025')",
    )
    statut: Literal["confirmé", "projet", "rumeur"]
    fiabilite: int = Field(ge=0, le=5)
    citation: str


class ClosureItem(BaseModel):
    bank: str
    agency_label: str = ""
    commune: str
    departement: Optional[str] = None
    region: Optional[str] = None
    address: str = ""
    closure_date: Optional[str] = None
    date_precision: Literal["exact", "month", "year", "approximate", "unknown"] = "unknown"
    status: Literal["confirmed", "announced", "contested", "threatened", "unclear"]
    closure_type: Literal["closure", "regroupement", "transfer", "merge", "threatened_closure"]
    is_physical_agency: bool = True
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = ""


class DeptSignal(BaseModel):
    bank: str
    departement: Optional[str] = None
    count: Optional[int] = None
    communes_mentioned: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence: str = ""


class VagueSignal(BaseModel):
    bank: str = ""
    scope: Literal["regional", "national", "unknown"] = "unknown"
    count: Optional[int] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence: str = ""


class ExtractionResult(BaseModel):
    article_type: Literal[
        "single_closure",
        "list_closures",
        "department_signal",
        "regional_signal",
        "national_signal",
        "social_hr",
        "out_of_scope",
        "ambiguous",
    ]
    source_reliability: Literal[
        "primary",
        "local_press",
        "national_press",
        "aggregator",
        "weak",
    ] = "weak"
    closures: list[ClosureItem] = Field(default_factory=list)
    department_signals: list[DeptSignal] = Field(default_factory=list)
    vague_signals: list[VagueSignal] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_sonnet: bool = False
    reason: str = ""


_INSTRUCTIONS_STRUCTURED = (
    "Tu analyses un article de presse français sur d'éventuelles fermetures, "
    "regroupements ou transferts d'agences BANCAIRES physiques en France. "
    "Classe l'article dans article_type. Pour chaque agence NOMMÉE (commune précise), "
    "ajoute un élément à closures[] ; si l'article cite plusieurs agences (article-liste), "
    "renvoie-les TOUTES. N'invente jamais de commune. "
    "Un signal départemental chiffré sans communes précises (ex. '10 agences dans le Cher') "
    "va dans department_signals[]. Un signal régional/national vague va dans vague_signals[]. "
    "is_physical_agency=false pour distributeur (DAB), service en ligne ou hors agence. "
    "closure_type: closure|regroupement|transfer|merge|threatened_closure. "
    "status: confirmed|announced|contested|threatened|unclear. "
    "date_precision et closure_date (ISO) si connues. "
    "confidence (0..1) par closure ET global. needs_sonnet=true si ambigu/complexe. "
    "evidence: courte citation textuelle justifiant. "
    "Cas La Banque Postale : un bureau de poste peut être une agence/point bancaire "
    "physique seulement si l'article relie explicitement la fermeture à La Banque "
    "Postale, aux services financiers/bancaires, à un conseiller bancaire, ou à la "
    "perte d'un service bancaire. Si l'article annonce la fermeture permanente d'un "
    "BUREAU DE POSTE nommé dans une commune précise, renvoie une closure La Banque "
    "Postale avec confidence modérée (0.45-0.65) même si le caractère bancaire doit "
    "être vérifié ensuite. Ne retiens pas les agences postales communales/relais sans "
    "indice bancaire explicite. Sinon classe en out_of_scope ou ambiguous."
)

_SONNET_REVIEW_INSTRUCTIONS = (
    "\n\nRELIS L'ARTICLE AVEC PLUS DE PRÉCISION. Haiku a signalé un cas "
    "ambigu ou peu fiable. Résous les ambiguïtés si possible, extrais TOUTES "
    "les agences bancaires physiques nommées, n'invente jamais de commune ni "
    "d'adresse, et mets needs_sonnet=false sauf si l'ambiguïté persiste."
)


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


def build_messages_structured(article: dict, aujourdhui: Optional[str] = None) -> list[dict]:
    aujourdhui = aujourdhui or date.today().isoformat()
    corps = (
        f"{_INSTRUCTIONS_STRUCTURED}\n\n"
        f"DATE DU JOUR: {aujourdhui}\n"
        f"TITRE: {article.get('titre','')}\n"
        f"TEXTE: {article.get('texte','')}\n"
        f"DÉPARTEMENT (indice): {article.get('departement')}"
    )
    return [{"role": "user", "content": corps}]


def build_messages_structured_sonnet(article: dict, aujourdhui: Optional[str] = None) -> list[dict]:
    messages = build_messages_structured(article, aujourdhui)
    return [{
        **messages[0],
        "content": f"{messages[0]['content']}{_SONNET_REVIEW_INSTRUCTIONS}",
    }]


def should_escalate_structured(result: ExtractionResult) -> bool:
    """True quand un résultat Haiku structuré mérite une relecture Sonnet."""
    if not getattr(config, "STRUCTURED_SONNET_ESCALATION_ENABLED", True):
        return False
    if result.needs_sonnet:
        return True
    if result.article_type == "ambiguous":
        return True
    threshold = getattr(config, "STRUCTURED_SONNET_MIN_CONFIDENCE", 0.65)
    if result.confidence < threshold:
        return True
    if result.article_type == "list_closures" and not result.closures:
        return True
    if result.article_type == "department_signal" and not result.department_signals:
        return True
    return False


def _retenir_fermeture(statut_temporel: str, date_fermeture: Optional[str],
                       floor: Optional[str], aujourdhui: str) -> bool:
    """True si la fermeture entre dans le périmètre temporel de la veille.

    - a_venir : toujours conservée (prévisionnel), même sans date.
    - deja_fermee / inconnu : conservée seulement si une date effective est
      connue ET >= plancher `floor`. Sans date exploitable -> non conservée
      (le pipeline la routera en vigilance).
    """
    if statut_temporel == "a_venir":
        return True
    if not date_fermeture:
        return False
    try:
        eff = date.fromisoformat(date_fermeture[:10])
    except ValueError:
        return False
    if floor:
        try:
            if eff < date.fromisoformat(floor[:10]):
                return False
        except ValueError:
            pass
    return True


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


def _parse_avec_retries(
    client,
    *,
    model: str,
    messages: list[dict],
    sleep_fn=time.sleep,
    output_format=Extraction,
    max_tokens: int = 1024,
):
    max_retries = max(0, _int_env("ANTHROPIC_MAX_RETRIES", _DEFAULT_MAX_RETRIES))
    base = max(0.0, _float_env("ANTHROPIC_RETRY_BASE_SECONDS", _DEFAULT_RETRY_BASE_SECONDS))
    plafond = max(base, _float_env("ANTHROPIC_RETRY_MAX_SECONDS", _DEFAULT_RETRY_MAX_SECONDS))
    for tentative in range(max_retries + 1):
        try:
            return client.messages.parse(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                output_format=output_format,
            )
        except Exception as exc:
            status = _status_code(exc)
            if status not in _RETRY_STATUS_CODES or tentative >= max_retries:
                raise
            attente = min(plafond, base * (2 ** tentative))
            print(f"[extractor] Anthropic {status} — nouvelle tentative dans {attente:g}s")
            sleep_fn(attente)


def _fallback_model(model: str) -> str | None:
    fallback = getattr(config, "ANTHROPIC_FALLBACK_MODEL", "")
    if not getattr(config, "ANTHROPIC_FALLBACK_ENABLED", True):
        return None
    if not fallback or fallback == model:
        return None
    return fallback


def _resultat_depuis_extraction(
    data: Extraction | None,
    article: dict,
    *,
    floor: Optional[str],
    aujourdhui: str,
) -> Optional[dict]:
    if data is None or not data.concerne_banque:
        return None
    if not _retenir_fermeture(data.statut_temporel, data.date_fermeture, floor, aujourdhui):
        return None
    banque = normalise_banque(data.banque)
    if normalise_cle(banque) in getattr(config, "EXCLURE_BANQUES", []):
        return None
    if not banque_connue(banque):
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
        "statut_temporel": data.statut_temporel,
        "date_fermeture_approx": 1 if data.date_fermeture_approx else 0,
        "fiabilite": data.fiabilite,
        "lat": None,
        "lon": None,
        "citation": data.citation,
    }


def extract(article: dict, client, model: str = config.ANTHROPIC_MODEL,
            aujourdhui: Optional[str] = None, floor: Optional[str] = None) -> Optional[dict]:
    aujourdhui = aujourdhui or date.today().isoformat()
    messages = build_messages(article, aujourdhui)
    fallback_model = _fallback_model(model)
    try:
        response = _parse_avec_retries(
            client,
            model=model,
            messages=messages,
        )
        data: Extraction = response.parsed_output
    except Exception as exc:
        if _status_code(exc) in _RETRY_STATUS_CODES and fallback_model:
            response = _parse_avec_retries(
                client,
                model=fallback_model,
                messages=messages,
            )
            data = response.parsed_output
        elif (
            _status_code(exc) in _RETRY_STATUS_CODES
            and os.environ.get("OPENAI_API_KEY")
            and os.environ.get("OPENAI_FALLBACK_ENABLED", "1") != "0"
        ):
            from backend.openai_fallback import extract_openai
            data = extract_openai(article, aujourdhui)
        else:
            raise
    result = _resultat_depuis_extraction(data, article, floor=floor, aujourdhui=aujourdhui)
    if result is not None or not fallback_model:
        return result
    try:
        response = _parse_avec_retries(
            client,
            model=fallback_model,
            messages=messages,
        )
        data = response.parsed_output
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
    return _resultat_depuis_extraction(data, article, floor=floor, aujourdhui=aujourdhui)


def extract_structured(
    article: dict,
    client,
    model: str = config.ANTHROPIC_MODEL,
    aujourdhui: Optional[str] = None,
) -> ExtractionResult:
    aujourdhui = aujourdhui or date.today().isoformat()
    messages = build_messages_structured(article, aujourdhui)
    fallback_model = _fallback_model(model)
    try:
        response = _parse_avec_retries(
            client,
            model=model,
            messages=messages,
            output_format=ExtractionResult,
            max_tokens=2048,
        )
        result = response.parsed_output
    except Exception as exc:
        if _status_code(exc) in _RETRY_STATUS_CODES and fallback_model:
            response = _parse_avec_retries(
                client,
                model=fallback_model,
                messages=messages,
                output_format=ExtractionResult,
                max_tokens=2048,
            )
            return response.parsed_output
        if (
            _status_code(exc) in _RETRY_STATUS_CODES
            and os.environ.get("OPENAI_API_KEY")
            and os.environ.get("OPENAI_FALLBACK_ENABLED", "1") != "0"
        ):
            from backend.openai_fallback import extract_openai_structured
            return extract_openai_structured(article, aujourdhui)
        raise
    if fallback_model and should_escalate_structured(result):
        try:
            response = _parse_avec_retries(
                client,
                model=fallback_model,
                messages=build_messages_structured_sonnet(article, aujourdhui),
                output_format=ExtractionResult,
                max_tokens=2048,
            )
            return response.parsed_output
        except Exception:
            return result
    return result
