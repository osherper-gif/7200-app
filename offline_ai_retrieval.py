import re
from collections import Counter
from typing import Any


_WORD_RE = re.compile(r"[A-Za-z0-9\u0590-\u05FF][A-Za-z0-9\u0590-\u05FF_\-/.]*")
_STOPWORDS = {
    "האם", "איך", "מה", "מתי", "למה", "של", "על", "עם", "בלי", "יש", "גם", "כל",
    "the", "and", "for", "with", "what", "how", "when", "why", "can", "does", "is", "are",
}
_TERM_MAP = {
    "shall": "must",
    "should": "must",
    "must": "must",
    "requirements": "requirement",
    "requirement": "requirement",
    "דרישה": "requirement",
    "דרישות": "requirement",
    "בדיקה": "test",
    "בדיקות": "test",
    "ממשק": "interface",
    "ממשקים": "interface",
    "ארכיטקטורה": "architecture",
    "מערכת": "system",
    "סיכון": "risk",
    "סיכונים": "risk",
}


def normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("״", '"').replace("׳", "'")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"[–—-]+", " ", text)
    text = re.sub(r"[^\w\u0590-\u05FF./ ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> list[str]:
    tokens = []
    for token in _WORD_RE.findall(normalize_text(text)):
        mapped = _TERM_MAP.get(token, token)
        if mapped and mapped not in _STOPWORDS and len(mapped) > 1:
            tokens.append(mapped)
    return tokens


def _token_overlap(question_tokens: list[str], item_tokens: list[str]) -> float:
    if not question_tokens or not item_tokens:
        return 0.0
    q_counter = Counter(question_tokens)
    i_counter = Counter(item_tokens)
    shared = sum(min(q_counter[token], i_counter[token]) for token in q_counter)
    return shared / max(len(set(question_tokens)), 1)


def _phrase_overlap(question_norm: str, item_norm: str) -> float:
    if not question_norm or not item_norm:
        return 0.0
    if question_norm in item_norm or item_norm in question_norm:
        return 1.0
    score = 0.0
    for phrase in question_norm.split():
        if len(phrase) > 3 and phrase in item_norm:
            score += 0.08
    return min(score, 0.4)


def score_item(question: str, item: dict[str, Any]) -> dict[str, Any]:
    question_tokens = tokenize(question)
    item_text = " ".join(
        [
            str(item.get("question") or ""),
            str(item.get("answer") or ""),
            str(item.get("topic") or ""),
            str(item.get("domain") or ""),
            str(item.get("category") or ""),
            str(item.get("failure_modes") or ""),
        ]
    )
    item_tokens = tokenize(item_text)
    question_norm = normalize_text(question)
    item_norm = normalize_text(item_text)
    overlap = _token_overlap(question_tokens, item_tokens)
    phrase = _phrase_overlap(question_norm, item_norm)
    exact_bonus = 0.2 if normalize_text(item.get("question") or "") == question_norm else 0.0
    hard_case_bonus = 0.12 if item.get("source") == "hard_cases" and overlap > 0.28 else 0.0
    score = overlap * 0.65 + phrase * 0.25 + exact_bonus + hard_case_bonus
    return {
        "item": item,
        "score": round(score, 4),
        "overlap": round(overlap, 4),
        "question_tokens": question_tokens,
        "item_tokens": item_tokens,
    }


def retrieve_items(question: str, items: list[dict[str, Any]], top_n: int = 5) -> list[dict[str, Any]]:
    scored = [score_item(question, item) for item in items]
    scored.sort(key=lambda record: (record["score"], record["overlap"]), reverse=True)
    return scored[:top_n]


def detect_contradiction(top_items: list[dict[str, Any]]) -> bool:
    if len(top_items) < 2:
        return False
    strong = [record for record in top_items if record["score"] >= 0.34]
    if len(strong) < 2:
        return False
    texts = [
        " ".join(
            [
                str(record["item"].get("question") or ""),
                str(record["item"].get("answer") or ""),
                str(record["item"].get("confidence_rules") or ""),
                str(record["item"].get("refusal_policy") or ""),
            ]
        )
        for record in strong[:3]
    ]
    if _has_approval_conflict(texts):
        return True
    if _has_version_conflict(texts):
        return True
    if _has_numeric_conflict(texts):
        return True
    return False


def summarize_missing_information(question: str, top_items: list[dict[str, Any]]) -> list[str]:
    missing = []
    q_norm = normalize_text(question)
    if re.search(r"\b(latency|status|version|result|approved|pass|fail|cdr|pdr|mtbf|availability)\b", q_norm):
        missing.append("חסר מקור מקומי עדכני עם נתון או סטטוס חד-משמעי")
    if re.search(r"(האם|can|is|are).*(עומד|מאושר|תקין|ready|approved|pass)", q_norm):
        missing.append("חסרה אסמכתה מקומית שמאמתת מצב נוכחי או תוצאת בדיקה")
    if not top_items or top_items[0]["score"] < 0.28:
        missing.append("לא נמצאו פריטי ידע מקומיים מספיק רלוונטיים")
    out = []
    for item in missing:
        if item not in out:
            out.append(item)
    return out


def coverage_strength(top_items: list[dict[str, Any]]) -> float:
    if not top_items:
        return 0.0
    weights = [record["score"] for record in top_items[:3]]
    return round(sum(weights) / max(len(weights), 1), 4)


def _extract_numbers(text: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:\.\d+)?\b", normalize_text(text)))


def _extract_versions(text: str) -> set[str]:
    return set(re.findall(r"\b(?:v(?:ersion)?\s*)?\d+(?:\.\d+){1,3}\b", normalize_text(text)))


def _has_approval_conflict(texts: list[str]) -> bool:
    normalized = [normalize_text(text) for text in texts if text]
    if len(normalized) < 2:
        return False
    positive = any(re.search(r"\b(approved|ready|pass|passed|מאושר|מוכן|עבר|תקין)\b", text) for text in normalized)
    negative = any(re.search(r"\b(rejected|not approved|failed|fail|blocked|לא מאושר|נדחה|נכשל|חסום)\b", text) for text in normalized)
    return positive and negative


def _has_version_conflict(texts: list[str]) -> bool:
    version_sets = [_extract_versions(text) for text in texts if text]
    version_sets = [versions for versions in version_sets if versions]
    if len(version_sets) < 2:
        return False
    combined = set().union(*version_sets)
    return len(combined) > 1


def _has_numeric_conflict(texts: list[str]) -> bool:
    number_sets = [_extract_numbers(text) for text in texts if text]
    number_sets = [numbers for numbers in number_sets if numbers]
    if len(number_sets) < 2:
        return False
    shared_context = any(
        re.search(r"\b(latency|mtbf|availability|throughput|rate|version|frequency|delay|latency|זמן|קצב|תדר|גרסה)\b", normalize_text(text))
        for text in texts
    )
    if not shared_context:
        return False
    combined = set().union(*number_sets)
    return len(combined) > 1 and not any(len(combined & numbers) >= 1 for numbers in number_sets if len(numbers) > 1)
