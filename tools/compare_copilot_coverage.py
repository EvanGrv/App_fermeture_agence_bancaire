"""Benchmark de couverture Copilot (Cycle 1, read-only).

Classe chaque ligne du fichier de référence Copilot sur deux axes :
  - couverture dans notre base (data.json) : present_on_map / present_unlocated /
    present_department / needs_research / rejected_with_reason / confirmed_missing ;
  - fiabilité de la source Copilot : high / medium / low (+ source_flag).

Ne modifie jamais le pipeline. Produit data/export/copilot_coverage.{csv,json}.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.dedup import normalise_cle
from tools.compare_expected_closures import _cle_banque, _cle_commune
import config

# Mapping positionnel des colonnes de l'Excel Copilot (en-tête banque = "²").
COPILOT_COLS: dict[str, int] = {
    "banque": 0, "agence_localisation": 1, "adresse": 2, "commune": 3,
    "departement": 4, "region": 5, "lat": 6, "lon": 7, "date_fermeture": 8,
    "precision_date": 9, "source": 10, "url": 11, "score": 14,
    "statut_copilot": 15, "commentaires": 16,
}
_RAW_COLS = {"lat", "lon"}  # conservés bruts (float), pas de .strip()


def _cell(values, idx):
    return values[idx] if idx < len(values) else None


def load_copilot_rows(path) -> list[dict]:
    """Charge l'Excel Copilot en liste de dicts (mapping positionnel)."""
    from openpyxl import load_workbook

    wb = load_workbook(Path(path), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    next(rows_iter, None)  # saute l'en-tête
    out: list[dict] = []
    for values in rows_iter:
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            continue
        row: dict = {}
        for champ, idx in COPILOT_COLS.items():
            v = _cell(values, idx)
            if champ in _RAW_COLS:
                row[champ] = v if v is not None else ""
            else:
                row[champ] = "" if v is None else str(v).strip()
        out.append(row)
    return out


# Table inverse {nom normalisé du département -> code}.
_DEPT_NAME_TO_CODE = {normalise_cle(nom): code for code, nom in config.DEPARTEMENTS.items()}


def _norm(s) -> str:
    return normalise_cle(s or "")


def dept_name_to_code(name) -> str | None:
    return _DEPT_NAME_TO_CODE.get(normalise_cle(name or "")) or None


def load_overrides(path) -> dict:
    """Charge tools/copilot_overrides.json. Fichier absent/None -> sections vides."""
    if not path or not Path(path).exists():
        return {"sources": [], "rows": []}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"sources": data.get("sources") or [], "rows": data.get("rows") or []}
