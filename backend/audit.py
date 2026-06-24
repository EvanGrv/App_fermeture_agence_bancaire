from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path

import config
from backend import validation
from backend.dedup import normalise_cle

SUSPICIOUS_TERMS = (
    "grève",
    "greve",
    "suppression de postes",
    "suppressions de postes",
    "plan social",
    "pse",
    "national",
    "réseau",
    "reseau",
)
_DATE_REVIEW_DAYS = 120


def _closure_geo(closure: dict) -> dict | None:
    if closure.get("lat") is None or closure.get("lon") is None:
        return None
    return {
        "lat": closure.get("lat"),
        "lon": closure.get("lon"),
        "departement": closure.get("departement"),
        "code_insee": closure.get("code_insee"),
    }


def _text(closure: dict) -> str:
    sources = " ".join(
        f"{source.get('titre', '')} {source.get('url', '')}"
        for source in closure.get("sources", [])
    )
    return f"{closure.get('citation', '')} {sources}".lower()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.date()


def _similar(a: str, b: str) -> bool:
    if not a or not b or a == b:
        return False
    if len(a) < 5 or len(b) < 5:
        return False
    return a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.84


def audit_data(data: dict, today: date | None = None) -> list[dict]:
    today = today or date.today()
    closures = data.get("closures", [])
    findings: list[dict] = []

    for closure in closures:
        ok, reason = validation.fermeture_publiable(closure, _closure_geo(closure))
        if not ok:
            findings.append({
                "severity": "error",
                "type": "closure_non_publiable",
                "id": closure.get("id", ""),
                "banque": closure.get("banque", ""),
                "commune": closure.get("commune", ""),
                "departement": closure.get("departement", ""),
                "code_insee": closure.get("code_insee", ""),
                "message": reason or "fermeture non publiable",
            })
        contenu = normalise_cle(_text(closure))
        if any(normalise_cle(term) in contenu for term in SUSPICIOUS_TERMS):
            findings.append({
                "severity": "warning",
                "type": "citation_suspecte",
                "id": closure.get("id", ""),
                "banque": closure.get("banque", ""),
                "commune": closure.get("commune", ""),
                "departement": closure.get("departement", ""),
                "code_insee": closure.get("code_insee", ""),
                "message": "citation/source évoque grève, postes, PSE ou plan national",
            })
        annonce = _parse_date(closure.get("date_annonce"))
        if not closure.get("date_fermeture") and annonce and (today - annonce).days >= _DATE_REVIEW_DAYS:
            findings.append({
                "severity": "warning",
                "type": "date_fermeture_absente",
                "id": closure.get("id", ""),
                "banque": closure.get("banque", ""),
                "commune": closure.get("commune", ""),
                "departement": closure.get("departement", ""),
                "code_insee": closure.get("code_insee", ""),
                "message": "article ancien sans date de fermeture explicite; à confirmer ou archiver",
            })

    for index, left in enumerate(closures):
        left_name = normalise_cle(left.get("commune") or "")
        for right in closures[index + 1:]:
            right_name = normalise_cle(right.get("commune") or "")
            if not _similar(left_name, right_name):
                continue
            if (left.get("code_insee") or left.get("departement")) == (
                right.get("code_insee") or right.get("departement")
            ):
                continue
            findings.append({
                "severity": "info",
                "type": "communes_proches",
                "id": f"{left.get('id', '')}|{right.get('id', '')}",
                "banque": f"{left.get('banque', '')} / {right.get('banque', '')}",
                "commune": f"{left.get('commune', '')} / {right.get('commune', '')}",
                "departement": f"{left.get('departement', '')} / {right.get('departement', '')}",
                "code_insee": f"{left.get('code_insee', '')} / {right.get('code_insee', '')}",
                "message": "noms proches mais localisations distinctes à vérifier visuellement",
            })
    return findings


def write_reports(data_path: Path = config.DATA_JSON, output_dir: Path = config.EXPORT_DIR) -> list[dict]:
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    findings = audit_data(data)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "extraction_audit.json"
    json_path.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = output_dir / "extraction_audit.csv"
    fields = ["severity", "type", "id", "banque", "commune", "departement", "code_insee", "message"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for finding in findings:
            writer.writerow({field: finding.get(field, "") for field in fields})
    return findings


def main() -> None:
    findings = write_reports()
    errors = sum(1 for item in findings if item.get("severity") == "error")
    warnings = sum(1 for item in findings if item.get("severity") == "warning")
    infos = sum(1 for item in findings if item.get("severity") == "info")
    print(f"Audit extraction: {errors} erreurs, {warnings} alertes, {infos} infos")
    print(f"Rapports: {config.EXPORT_DIR / 'extraction_audit.csv'}")


if __name__ == "__main__":
    main()
