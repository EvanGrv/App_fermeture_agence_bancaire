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
        closures.append(cl)
        dep = cl["departement"]
        if dep:
            compteur[dep] = compteur.get(dep, 0) + 1
    departements = {
        code: {"nom": config.DEPARTEMENTS.get(code, code), "count": compteur.get(code, 0)}
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
