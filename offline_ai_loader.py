import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = ROOT_DIR / "ai_assets"
DATASET_PATH = ASSETS_DIR / "offline_ai_training_dataset_1200.json"
HARD_CASES_PATH = ASSETS_DIR / "offline_ai_training_hard_cases_600.json"
PROMPT_PATH = ASSETS_DIR / "codex_prompt_offline_ai_module.md"


def _read_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, list) else []


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _normalize_item(item: dict[str, Any], source_name: str) -> dict[str, Any]:
    evidence_parts = [
        str(item.get("question") or ""),
        str(item.get("answer") or ""),
        str(item.get("topic") or item.get("category") or ""),
        str(item.get("domain") or item.get("category") or ""),
        str(item.get("failure_modes") or ""),
        str(item.get("confidence_rules") or ""),
        str(item.get("refusal_policy") or ""),
    ]
    return {
        "id": str(item.get("id") or "").strip(),
        "source": source_name,
        "question": str(item.get("question") or "").strip(),
        "answer": str(item.get("answer") or "").strip(),
        "domain": str(item.get("domain") or "").strip(),
        "topic": str(item.get("topic") or item.get("category") or "").strip(),
        "role": str(item.get("role") or "").strip(),
        "category": str(item.get("category") or "").strip(),
        "difficulty": str(item.get("difficulty") or "").strip(),
        "expected_behavior": str(item.get("expected_behavior") or "").strip(),
        "response_pattern": str(item.get("response_pattern") or "").strip(),
        "confidence_rules": str(item.get("confidence_rules") or "").strip(),
        "refusal_policy": str(item.get("refusal_policy") or "").strip(),
        "failure_modes": str(item.get("failure_modes") or "").strip(),
        "negative_examples": item.get("negative_examples") or [],
        "answer_style": item.get("answer_style") or {},
        "good_answer_shape": item.get("good_answer_shape") or {},
        "metadata": item.get("metadata") or {},
        "evidence_text": " ".join(part for part in evidence_parts if part).strip(),
        "raw": item,
    }


@lru_cache(maxsize=1)
def load_knowledge_source() -> dict[str, Any]:
    dataset_items = [_normalize_item(item, "dataset") for item in _read_json(DATASET_PATH)]
    hard_case_items = [_normalize_item(item, "hard_cases") for item in _read_json(HARD_CASES_PATH)]
    return {
        "items": dataset_items + hard_case_items,
        "prompt": _read_text(PROMPT_PATH),
        "paths": {
            "dataset": str(DATASET_PATH),
            "hard_cases": str(HARD_CASES_PATH),
            "prompt": str(PROMPT_PATH),
        },
    }
