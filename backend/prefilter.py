"""Préfiltre local (Cycle 2b) : booléen historique + scoring/entités sans IA."""
import re
import unicodedata
from dataclasses import dataclass, field

import config
from backend.drilldown import communes_candidates
from backend.extractor import normalise_banque


def _normalise(texte: str) -> str:
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn"
    )
    return sans_accents.lower()


_VARIANTES = config.ENSEIGNES + [
    v for vs in getattr(config, "MARQUES_REGIONALES", {}).values() for v in vs
]
# (forme normalisée, forme canonique) triée du plus long au plus court.
_VARIANTE_PAIRS = sorted(
    {(_normalise(v), normalise_banque(v)) for v in _VARIANTES},
    key=lambda p: len(p[0]), reverse=True,
)
_ENSEIGNES_N = [n for n, _ in _VARIANTE_PAIRS]
_TERMES_N = [_normalise(t) for t in config.TERMES_FERMETURE]
_RH_N = [_normalise(t) for t in getattr(config, "RH_TERMS", [])]
_POSTAL_POINT_N = [_normalise(t) for t in getattr(config, "POSTAL_POINT_TERMS", [])]
_POSTAL_BANKING_N = [_normalise(t) for t in getattr(config, "POSTAL_BANKING_TERMS", [])]

_MOIS = ("janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|"
         "septembre|octobre|novembre|decembre|décembre")
_DATE_RE = re.compile(
    r"\b\d{1,2}\s*(?:er)?\s+(?:" + _MOIS + r")\s+\d{4}\b"
    r"|\b(?:" + _MOIS + r")\s+\d{4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:courant|fin|debut|début|mi|au\s+printemps|a\s+l'automne|en)\s+\d{4}\b",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(
    r"\b\d{1,3}(?:\s*(?:bis|ter))?\s+"
    r"(?:rue|avenue|av\.?|bd|boulevard|place|impasse|route|all[ée]e|chemin|quai|cours)\b"
    r".{0,60}",
    re.IGNORECASE,
)
_DEPT_CODE_RE = re.compile(r"\((\d{2,3}[ab]?|2[ab])\)", re.IGNORECASE)
_SENT_SPLIT = re.compile(r"[.!?\n]+")


@dataclass
class PrefilterResult:
    score: int
    banks: list[str] = field(default_factory=list)
    communes: list[str] = field(default_factory=list)
    departements: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    relevant_sentences: list[str] = field(default_factory=list)
    compact_context: str = ""


def _detect_banks(contenu_norm: str) -> list:
    found: list = []
    for norm, canon in _VARIANTE_PAIRS:
        if norm in contenu_norm and canon not in found:
            found.append(canon)
    if _is_postal_closure_candidate_norm(contenu_norm) and "La Banque Postale" not in found:
        found.append("La Banque Postale")
    return found


def _is_postal_closure_candidate_norm(contenu_norm: str) -> bool:
    a_point_postal = any(t in contenu_norm for t in _POSTAL_POINT_N)
    a_terme = any(t in contenu_norm for t in _TERMES_N)
    if not (a_point_postal and a_terme):
        return False
    # Un bureau de poste ordinaire est un candidat LBP. Les agences postales
    # communales/relais sont plus fragiles : elles ne passent que si un indice
    # bancaire explicite apparaît dans l'article.
    is_partner_point = (
        "agence postale communale" in contenu_norm
        or "relais poste" in contenu_norm
        or "relais postal" in contenu_norm
    )
    if is_partner_point and not any(t in contenu_norm for t in _POSTAL_BANKING_N):
        return False
    return True


def is_postal_closure_candidate(article: dict) -> bool:
    contenu = _normalise(f"{article.get('titre', '')} {article.get('texte', '')}")
    return _is_postal_closure_candidate_norm(contenu)


def _detect_departements(contenu: str, contenu_norm: str) -> list:
    deps: list = []
    for code, nom in config.DEPARTEMENTS.items():
        nom_norm = _normalise(nom)
        if re.search(r"\b" + re.escape(nom_norm) + r"\b", contenu_norm) and code not in deps:
            deps.append(code)
    for m in _DEPT_CODE_RE.finditer(contenu):
        code = m.group(1)
        if code not in deps:
            deps.append(code)
    return deps


def _split_sentences(texte: str) -> list:
    return [s.strip() for s in _SENT_SPLIT.split(texte) if s.strip()]


def is_relevant(article: dict) -> bool:
    contenu = _normalise(f"{article.get('titre', '')} {article.get('texte', '')}")
    a_enseigne = any(e in contenu for e in _ENSEIGNES_N)
    a_terme = any(t in contenu for t in _TERMES_N)
    return (a_enseigne and a_terme) or _is_postal_closure_candidate_norm(contenu)


def analyse(article: dict) -> PrefilterResult:
    titre = article.get("titre", "") or ""
    texte = article.get("texte", "") or ""
    titre_n = _normalise(titre)
    contenu = f"{titre} {texte}"
    contenu_n = _normalise(contenu)

    banks = _detect_banks(contenu_n)
    departements = _detect_departements(contenu, contenu_n)
    dates = [m.group(0) for m in _DATE_RE.finditer(contenu)]
    addresses = [m.group(0).strip() for m in _ADDRESS_RE.finditer(contenu)]

    communes: list = []
    relevant_sentences: list = []
    phrase_hit = False
    for s in _split_sentences(f"{titre}. {texte}"):
        sn = _normalise(s)
        s_bank = any(n in sn for n in _ENSEIGNES_N)
        s_term = any(t in sn for t in _TERMES_N)
        s_postal = _is_postal_closure_candidate_norm(sn)
        s_comm = communes_candidates(s)
        for c in s_comm:
            if c not in communes:
                communes.append(c)
        if ((s_bank and s_term) or s_postal) and s_comm:
            phrase_hit = True
            relevant_sentences.append(s)
        elif s_bank or s_term or s_postal:
            relevant_sentences.append(s)

    score = 0
    titre_bank = any(n in titre_n for n in _ENSEIGNES_N)
    titre_ferm = any(t in titre_n for t in _TERMES_N) or "agence" in titre_n
    if titre_bank and titre_ferm:
        score += 3
    if _is_postal_closure_candidate_norm(titre_n):
        score += 3
    if phrase_hit:
        score += 3
    if len(communes) >= 2:
        score += 2
    if dates:
        score += 2
    if addresses:
        score += 1

    has_term = any(t in contenu_n for t in _TERMES_N)
    if not banks and not has_term and not _is_postal_closure_candidate_norm(contenu_n):
        score -= 3
    if _RH_N and any(r in contenu_n for r in _RH_N) and "agence" not in contenu_n:
        score -= 2

    return PrefilterResult(
        score=score, banks=banks, communes=communes, departements=departements,
        dates=dates, addresses=addresses, relevant_sentences=relevant_sentences,
    )
