import csv
import json
import re
from datetime import datetime, timezone
import config
from backend.plans import PLANS
from backend.source_tier import tier as _source_tier
from backend.dedup import normalise_cle
from backend.vigilance_review import candidats_communes, signal_fermeture_agence

_CLOSURE_COLS = ["id", "banque", "commune", "code_insee", "departement", "type",
                 "date_annonce", "date_fermeture", "statut", "statut_temporel",
                 "date_fermeture_approx", "fiabilite", "lat", "lon", "citation",
                 "adresse", "agence_localisation", "commune_originale",
                 "created_at"]
_VIGILANCE_COLS = ["id", "banque", "departement", "titre", "extrait", "url",
                   "source", "date", "score", "raison", "created_at"]
_REGIONS = {
    "Auvergne-Rhône-Alpes": {"01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"},
    "Bourgogne-Franche-Comté": {"21", "25", "39", "58", "70", "71", "89", "90"},
    "Bretagne": {"22", "29", "35", "56"},
    "Centre-Val de Loire": {"18", "28", "36", "37", "41", "45"},
    "Corse": {"2A", "2B"},
    "Grand Est": {"08", "10", "51", "52", "54", "55", "57", "67", "68", "88"},
    "Hauts-de-France": {"02", "59", "60", "62", "80"},
    "Île-de-France": {"75", "77", "78", "91", "92", "93", "94", "95"},
    "Normandie": {"14", "27", "50", "61", "76"},
    "Nouvelle-Aquitaine": {"16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87"},
    "Occitanie": {"09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82"},
    "Pays de la Loire": {"44", "49", "53", "72", "85"},
    "Provence-Alpes-Côte d'Azur": {"04", "05", "06", "13", "83", "84"},
    "Guadeloupe": {"971"},
    "Martinique": {"972"},
    "Guyane": {"973"},
    "La Réunion": {"974"},
    "Mayotte": {"976"},
}


def build_payload(conn) -> dict:
    closures = []
    compteur = {}
    for row in conn.execute(f"SELECT {','.join(_CLOSURE_COLS)} FROM closures"):
        cl = dict(zip(_CLOSURE_COLS, row))
        srcs = conn.execute(
            "SELECT url, titre, source, date FROM sources WHERE closure_id=?",
            (cl["id"],),
        ).fetchall()
        cl["sources"] = [
            {"url": u, "titre": t, "source": s, "date": d, "tier": _source_tier(u or "")}
            for (u, t, s, d) in srcs
        ]
        controle = conn.execute(
            "SELECT etat_administratif, siret, source FROM controles_sirene WHERE closure_id=?",
            (cl["id"],),
        ).fetchone()
        if controle:
            cl["controle_sirene"] = {
                "etat_administratif": controle[0],
                "siret": controle[1],
                "source": controle[2],
            }
        cl["region"] = _region(cl["departement"])
        closures.append(cl)
        dep = cl["departement"]
        if dep:
            compteur[dep] = compteur.get(dep, 0) + 1
    agences = {
        dep: total
        for dep, total in conn.execute(
            "SELECT departement, COUNT(*) FROM referentiel WHERE departement IS NOT NULL GROUP BY departement"
        )
    }
    departements = {
        code: {
            "nom": config.DEPARTEMENTS.get(code, code),
            "region": _region(code),
            "count": compteur.get(code, 0),
            "total_agences": agences.get(code, 0),
        }
        for code in config.DEPARTEMENTS
    }
    vigilances = [
        dict(zip(_VIGILANCE_COLS, row))
        for row in conn.execute(
            f"SELECT {','.join(_VIGILANCE_COLS)} FROM vigilances ORDER BY score DESC, date DESC"
        )
    ]
    department_estimates = _build_department_estimates(closures, vigilances)
    for code, dep in departements.items():
        estimate = department_estimates.get(code, {})
        dep["precise_count"] = estimate.get("precise_count", dep["count"])
        dep["unlocated_count"] = estimate.get("unlocated_count", 0)
        dep["estimated_count"] = estimate.get("estimated_count", dep["count"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "departements": departements,
        "department_estimates": department_estimates,
        "regions": _build_regions(closures),
        "closures": closures,
        "vigilances": vigilances,
        "plans": PLANS,
    }


_VAGUE_SIGNAL_RE = re.compile(
    r"\b(\d+|plusieurs|des|ces|les)\s+agences?\b|"
    r"\bfermetures?\s+d[’']agences\b|"
    r"\b(r[ée]seau|région|region|département|departement|national|"
    r"france|plan|restructuration|suppressions?\s+de\s+postes)\b",
    re.IGNORECASE,
)


def _signal_departemental(v: dict, represented: set[tuple[str, str]]) -> dict | None:
    """Signal comptable mais non pointable précisément, très conservateur.

    On exclut volontairement les annonces de volume ("10 agences ferment dans
    l'Aude") et on ne retient qu'un signal local singulier, déjà rattaché à un
    département et avec une commune/localisation nommée dans le titre/extrait.
    """
    dep = str(v.get("departement") or "").strip()
    banque = v.get("banque")
    if dep not in config.DEPARTEMENTS or not banque:
        return None
    texte = f"{v.get('titre') or ''} {v.get('extrait') or ''}"
    if not signal_fermeture_agence(texte) or _VAGUE_SIGNAL_RE.search(texte):
        return None
    communes = candidats_communes(texte, banque)
    if len(communes) != 1:
        return None
    commune = communes[0]
    key = (normalise_cle(banque), normalise_cle(commune))
    if key in represented:
        return None
    return {
        "id": v.get("id"),
        "banque": banque,
        "commune": commune,
        "departement": dep,
        "titre": v.get("titre") or "",
        "source": v.get("source") or "",
        "url": v.get("url") or "",
        "score": v.get("score") or 0,
        "precision": "departement",
        "reason": "signal local non pointé précisément",
    }


def _build_department_estimates(closures: list[dict], vigilances: list[dict]) -> dict:
    estimates: dict[str, dict] = {}
    represented = {
        (normalise_cle(c.get("banque") or ""), normalise_cle(c.get("commune") or ""))
        for c in closures
        if c.get("banque") and c.get("commune")
    }
    for cl in closures:
        dep = cl.get("departement")
        if dep not in config.DEPARTEMENTS:
            continue
        bucket = estimates.setdefault(dep, {
            "departement": dep,
            "nom": config.DEPARTEMENTS.get(dep, dep),
            "precise_count": 0,
            "unlocated_count": 0,
            "estimated_count": 0,
            "signals": [],
        })
        bucket["precise_count"] += 1
    seen_signals: set[str] = set()
    for vig in vigilances:
        signal = _signal_departemental(vig, represented)
        if not signal or signal["id"] in seen_signals:
            continue
        seen_signals.add(signal["id"])
        dep = signal["departement"]
        bucket = estimates.setdefault(dep, {
            "departement": dep,
            "nom": config.DEPARTEMENTS.get(dep, dep),
            "precise_count": 0,
            "unlocated_count": 0,
            "estimated_count": 0,
            "signals": [],
        })
        bucket["signals"].append(signal)
        bucket["unlocated_count"] += 1
    for bucket in estimates.values():
        bucket["estimated_count"] = bucket["precise_count"] + bucket["unlocated_count"]
        bucket["signals"].sort(key=lambda item: (-(item.get("score") or 0), item.get("banque") or ""))
    return estimates


def _build_regions(closures: list[dict]) -> list[dict]:
    """Agrège les fermetures par région pour l'onglet veille & articles.

    Une région n'apparaît que si au moins une fermeture y est rattachée.
    Le décompte d'articles correspond au nombre de sources de presse reliées.
    """
    agg: dict[str, dict] = {}
    for cl in closures:
        region = cl.get("region")
        if not region:
            continue
        bucket = agg.setdefault(region, {
            "region": region,
            "articles": 0,
            "fermetures": 0,
            "projets": 0,
            "fusions": 0,
            "departements": set(),
        })
        sources = [s for s in (cl.get("sources") or []) if s.get("url")]
        bucket["articles"] += max(1, len(sources))
        if cl.get("type") == "fusion":
            bucket["fusions"] += 1
        elif cl.get("statut") == "projet":
            bucket["projets"] += 1
        else:
            bucket["fermetures"] += 1
        if cl.get("departement"):
            bucket["departements"].add(cl["departement"])
    regions = []
    for bucket in agg.values():
        types = []
        if bucket["fermetures"]:
            types.append("Fermeture")
        if bucket["projets"]:
            types.append("Projet")
        if bucket["fusions"]:
            types.append("Fusion")
        regions.append({
            "region": bucket["region"],
            "articles": bucket["articles"],
            "fermetures": bucket["fermetures"],
            "projets": bucket["projets"],
            "fusions": bucket["fusions"],
            "types": types,
            "departements": sorted(bucket["departements"]),
            "nb_departements": len(bucket["departements"]),
        })
    regions.sort(key=lambda item: item["articles"], reverse=True)
    return regions


def export_json(conn, path) -> None:
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(conn)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _region(departement: str | None) -> str:
    for region, deps in _REGIONS.items():
        if departement in deps:
            return region
    return ""


def export_fermetures_csv(conn, path) -> None:
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(conn)
    fields = [
        "Banque", "Commune", "Département", "Région", "Type d'information",
        "Temporalité",
        "Date annonce", "Date fermeture", "Source", "URL", "Fiabilité",
        "À vérifier", "Citation",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for closure in payload["closures"]:
            source = (closure.get("sources") or [{}])[0]
            a_verifier = (
                not closure.get("date_fermeture")
                or int(closure.get("fiabilite") or 0) < 4
                or closure.get("statut") != "confirmé"
            )
            writer.writerow({
                "Banque": closure.get("banque") or "",
                "Commune": closure.get("commune") or "",
                "Département": closure.get("departement") or "",
                "Région": _region(closure.get("departement")),
                "Type d'information": closure.get("type") or "",
                "Temporalité": {"deja_fermee": "Déjà fermée", "a_venir": "À venir"}
                    .get(closure.get("statut_temporel"), "Inconnu"),
                "Date annonce": closure.get("date_annonce") or "",
                "Date fermeture": closure.get("date_fermeture") or "",
                "Source": source.get("source") or "",
                "URL": source.get("url") or "",
                "Fiabilité": closure.get("fiabilite") or "",
                "À vérifier": "oui" if a_verifier else "non",
                "Citation": closure.get("citation") or "",
            })
