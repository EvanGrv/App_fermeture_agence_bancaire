import json
from datetime import datetime, timezone
import config
from backend.plans import PLANS

_CLOSURE_COLS = ["id", "banque", "commune", "code_insee", "departement", "type",
                 "date_annonce", "date_fermeture", "statut", "fiabilite",
                 "lat", "lon", "citation", "created_at"]


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
            {"url": u, "titre": t, "source": s, "date": d} for (u, t, s, d) in srcs
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
            "count": compteur.get(code, 0),
            "total_agences": agences.get(code, 0),
        }
        for code in config.DEPARTEMENTS
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "departements": departements,
        "closures": closures,
        "plans": PLANS,
    }


def export_json(conn, path) -> None:
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(conn)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
