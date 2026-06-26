import csv
import json
from datetime import datetime, timezone
import config
from backend.plans import PLANS
from backend.source_tier import tier as _source_tier

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
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "departements": departements,
        "regions": _build_regions(closures),
        "closures": closures,
        "vigilances": vigilances,
        "plans": PLANS,
    }


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
