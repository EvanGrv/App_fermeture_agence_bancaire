import json
import os
from datetime import datetime, timezone

import requests
from pydantic import ValidationError

import config
from backend.extractor import (
    Extraction,
    ExtractionResult,
    build_messages,
    build_messages_structured,
)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-5.4-nano"
DEFAULT_BUDGET_EUR = 1.0
DEFAULT_MAX_OUTPUT_TOKENS = 700

# Prix standard gpt-5.4-nano, par million de tokens, d'après la grille OpenAI.
DEFAULT_INPUT_EUR_PER_M = 0.20
DEFAULT_OUTPUT_EUR_PER_M = 1.25


class OpenAIBudgetExceeded(RuntimeError):
    pass


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _budget_path():
    return config.CACHE_DIR / "openai_budget.json"


def _load_budget(path=None) -> dict:
    path = path or _budget_path()
    if not path.exists():
        return {"spent_eur": 0.0, "calls": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"spent_eur": 0.0, "calls": 0}


def _save_budget(data: dict, path=None) -> None:
    path = path or _budget_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _token_estimate(messages: list[dict]) -> int:
    texte = "\n".join(str(m.get("content", "")) for m in messages)
    return max(1, len(texte) // 4)


def _cout(input_tokens: int, output_tokens: int) -> float:
    input_rate = _float_env("OPENAI_INPUT_EUR_PER_M", DEFAULT_INPUT_EUR_PER_M)
    output_rate = _float_env("OPENAI_OUTPUT_EUR_PER_M", DEFAULT_OUTPUT_EUR_PER_M)
    return (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate


def _assert_budget(input_tokens: int, output_tokens: int, budget_path=None) -> None:
    budget = _float_env("OPENAI_BUDGET_EUR", DEFAULT_BUDGET_EUR)
    spent = float(_load_budget(budget_path).get("spent_eur", 0.0))
    estimate = _cout(input_tokens, output_tokens)
    if spent + estimate > budget:
        raise OpenAIBudgetExceeded(
            f"budget OpenAI dépassé: {spent + estimate:.4f} > {budget:.4f}"
        )


def _record_usage(input_tokens: int, output_tokens: int, budget_path=None) -> None:
    data = _load_budget(budget_path)
    cout = _cout(input_tokens, output_tokens)
    data["spent_eur"] = float(data.get("spent_eur", 0.0)) + cout
    data["calls"] = int(data.get("calls", 0)) + 1
    data["last_input_tokens"] = input_tokens
    data["last_output_tokens"] = output_tokens
    data["last_cost_eur"] = cout
    _save_budget(data, budget_path)


def _schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "concerne_banque", "banque", "commune", "departement", "type",
            "statut_temporel", "date_fermeture", "date_fermeture_approx", "statut", "fiabilite", "citation",
        ],
        "properties": {
            "concerne_banque": {"type": "boolean"},
            "banque": {"type": "string"},
            "commune": {"type": "string"},
            "departement": {"type": ["string", "null"]},
            "type": {"type": "string", "enum": ["fermeture", "fusion"]},
            "statut_temporel": {
                "type": "string",
                "enum": ["a_venir", "deja_fermee", "inconnu"],
            },
            "date_fermeture": {"type": ["string", "null"]},
            "date_fermeture_approx": {"type": "boolean"},
            "statut": {"type": "string", "enum": ["confirmé", "projet", "rumeur"]},
            "fiabilite": {"type": "integer", "minimum": 0, "maximum": 5},
            "citation": {"type": "string"},
        },
    }


def _schema_structured() -> dict:
    closure = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "bank",
            "agency_label",
            "commune",
            "departement",
            "region",
            "address",
            "closure_date",
            "date_precision",
            "status",
            "closure_type",
            "is_physical_agency",
            "confidence",
            "evidence",
        ],
        "properties": {
            "bank": {"type": "string"},
            "agency_label": {"type": "string"},
            "commune": {"type": "string"},
            "departement": {"type": ["string", "null"]},
            "region": {"type": ["string", "null"]},
            "address": {"type": "string"},
            "closure_date": {"type": ["string", "null"]},
            "date_precision": {
                "type": "string",
                "enum": ["exact", "month", "year", "approximate", "unknown"],
            },
            "status": {
                "type": "string",
                "enum": ["confirmed", "announced", "contested", "threatened", "unclear"],
            },
            "closure_type": {
                "type": "string",
                "enum": [
                    "closure",
                    "regroupement",
                    "transfer",
                    "merge",
                    "threatened_closure",
                ],
            },
            "is_physical_agency": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "string"},
        },
    }
    dept = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "bank",
            "departement",
            "count",
            "communes_mentioned",
            "confidence",
            "evidence",
        ],
        "properties": {
            "bank": {"type": "string"},
            "departement": {"type": ["string", "null"]},
            "count": {"type": ["integer", "null"]},
            "communes_mentioned": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "string"},
        },
    }
    vague = {
        "type": "object",
        "additionalProperties": False,
        "required": ["bank", "scope", "count", "confidence", "evidence"],
        "properties": {
            "bank": {"type": "string"},
            "scope": {"type": "string", "enum": ["regional", "national", "unknown"]},
            "count": {"type": ["integer", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "article_type",
            "source_reliability",
            "closures",
            "department_signals",
            "vague_signals",
            "confidence",
            "needs_sonnet",
            "reason",
        ],
        "properties": {
            "article_type": {
                "type": "string",
                "enum": [
                    "single_closure",
                    "list_closures",
                    "department_signal",
                    "regional_signal",
                    "national_signal",
                    "social_hr",
                    "out_of_scope",
                    "ambiguous",
                ],
            },
            "source_reliability": {
                "type": "string",
                "enum": ["primary", "local_press", "national_press", "aggregator", "weak"],
            },
            "closures": {"type": "array", "items": closure},
            "department_signals": {"type": "array", "items": dept},
            "vague_signals": {"type": "array", "items": vague},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "needs_sonnet": {"type": "boolean"},
            "reason": {"type": "string"},
        },
    }


def extract_openai(article: dict, aujourdhui: str, fetch=None, budget_path=None) -> Extraction:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY absente")

    fetch = fetch or _post
    model = os.environ.get("OPENAI_FALLBACK_MODEL", DEFAULT_MODEL)
    max_output = int(_float_env("OPENAI_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS))
    messages = build_messages(article, aujourdhui)
    input_estimate = _token_estimate(messages)
    _assert_budget(input_estimate, max_output, budget_path)

    payload = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_output,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "extraction_fermeture_bancaire",
                "strict": True,
                "schema": _schema(),
            },
        },
    }
    response = fetch(OPENAI_CHAT_URL, api_key, payload)
    usage = response.get("usage") or {}
    input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or input_estimate
    output_tokens = (
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or max_output
    )
    _record_usage(int(input_tokens), int(output_tokens), budget_path)
    content = response["choices"][0]["message"]["content"]
    try:
        return Extraction.model_validate_json(content)
    except ValidationError:
        return Extraction.model_validate(json.loads(content))


def extract_openai_structured(
    article: dict,
    aujourdhui: str,
    fetch=None,
    budget_path=None,
) -> ExtractionResult:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY absente")

    fetch = fetch or _post
    model = os.environ.get("OPENAI_FALLBACK_MODEL", DEFAULT_MODEL)
    max_output = int(_float_env("OPENAI_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS))
    messages = build_messages_structured(article, aujourdhui)
    input_estimate = _token_estimate(messages)
    _assert_budget(input_estimate, max_output, budget_path)

    payload = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_output,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "extraction_structuree",
                "strict": True,
                "schema": _schema_structured(),
            },
        },
    }
    response = fetch(OPENAI_CHAT_URL, api_key, payload)
    usage = response.get("usage") or {}
    input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or input_estimate
    output_tokens = (
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or max_output
    )
    _record_usage(int(input_tokens), int(output_tokens), budget_path)
    content = response["choices"][0]["message"]["content"]
    return ExtractionResult.model_validate_json(content)


def _post(url: str, api_key: str, payload: dict) -> dict:
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()
