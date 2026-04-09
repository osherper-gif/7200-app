import re

from offline_ai_retrieval import coverage_strength, detect_contradiction, summarize_missing_information


def evaluate_confidence(question: str, retrieved: list[dict], strict_refusal: bool = True):
    missing = summarize_missing_information(question, retrieved)
    contradiction = detect_contradiction(retrieved)
    strength = coverage_strength(retrieved)
    critical_fact_question = _is_critical_fact_question(question)

    if contradiction and critical_fact_question:
        missing = _dedupe(missing + ["יש סתירה בין פריטי הידע המקומיים הרלוונטיים"])
        return "low", True if strict_refusal else True, missing, "לאתר מקור מקומי מוסמך אחד וליישב את הסתירה לפני החלטה.", {
            "contradiction": contradiction,
            "is_critical_fact_question": critical_fact_question,
            "coverage_strength": strength,
            "decision_path": "critical_contradiction_refusal",
        }

    if not retrieved or strength < 0.28:
        missing = _dedupe(missing or ["אין פריטי ידע מקומיים מספיק רלוונטיים לשאלה הזו"])
        return "low", True, missing, "להוסיף מקור מקומי רלוונטי או לנסח את השאלה בצורה ממוקדת יותר.", {
            "contradiction": contradiction,
            "is_critical_fact_question": critical_fact_question,
            "coverage_strength": strength,
            "decision_path": "insufficient_retrieval_refusal",
        }

    if missing:
        return "low", True if strict_refusal else False, _dedupe(missing), "לאסוף את המידע החסר מהמסמך או מהגרסה המאושרת לפני קביעה.", {
            "contradiction": contradiction,
            "is_critical_fact_question": critical_fact_question,
            "coverage_strength": strength,
            "decision_path": "missing_information_refusal" if strict_refusal else "missing_information_low_confidence",
        }

    if strength >= 0.62 and len([record for record in retrieved if record["score"] >= 0.45]) >= 2:
        return "high", False, [], "לאמת את המסקנה מול המסמך המקומי הרלוונטי ולהמשיך לצעד הבא.", {
            "contradiction": contradiction,
            "is_critical_fact_question": critical_fact_question,
            "coverage_strength": strength,
            "decision_path": "high_confidence_answer",
        }

    if contradiction and not critical_fact_question:
        return "medium", False, [], "להצליב את ההמלצה מול המקור המקומי הקרוב ביותר לפני החלטת תכן.", {
            "contradiction": contradiction,
            "is_critical_fact_question": critical_fact_question,
            "coverage_strength": strength,
            "decision_path": "noncritical_contradiction_synthesis",
        }

    return "medium", False, [], "לאמת את המסקנה מול המסמך המקומי הקרוב ביותר לפני יישום.", {
        "contradiction": contradiction,
        "is_critical_fact_question": critical_fact_question,
        "coverage_strength": strength,
        "decision_path": "medium_confidence_answer",
    }


def compose_response(question: str, retrieved: list[dict], confidence: str, refusal: bool, missing_information: list[str], recommended_action: str) -> dict:
    used_items = [record["item"]["id"] for record in retrieved[:3] if record["item"].get("id")]

    if refusal:
        reason = missing_information[0] if missing_information else "אין בסיס מקומי מספיק"
        answer = (
            "אין לי מספיק מידע מקומי כדי לקבוע.\n"
            f"למה: {reason}.\n"
            f"צעד מעשי הבא: {recommended_action}"
        )
        return {
            "answer": answer,
            "confidence": "low",
            "used_items": used_items,
            "missing_information": missing_information or ["אין מידע מקומי מספיק"],
            "recommended_action": recommended_action,
            "refusal": True,
        }

    conclusion = _build_human_conclusion(question, retrieved)
    explanation = _build_human_explanation(question, retrieved)
    answer = (
        f"{conclusion}\n"
        f"למה: {explanation}\n"
        f"צעד מעשי הבא: {recommended_action}"
    )
    return {
        "answer": answer,
        "confidence": confidence,
        "used_items": used_items,
        "missing_information": missing_information,
        "recommended_action": recommended_action,
        "refusal": False,
    }


def _build_human_conclusion(question: str, retrieved: list[dict]) -> str:
    if _is_general_engineering_question(question):
        summary = _summarize_engineering_direction(retrieved)
        if summary:
            return f"בקצרה: {summary}"

    lead = _sanitize_answer_text(_best_item_text(retrieved[:2]))
    sentence = _normalize_sentence_start(_first_sentence(lead))
    if not sentence:
        return "בקצרה: יש כאן כיוון הנדסי סביר, אבל חשוב להישען על המידע המקומי הזמין."
    if len(sentence) > 180:
        sentence = sentence[:177].rstrip() + "..."
    return sentence if sentence.startswith("בקצרה:") else f"בקצרה: {sentence}"


def _build_human_explanation(question: str, retrieved: list[dict]) -> str:
    if _is_general_engineering_question(question):
        themes = _collect_theme_terms(retrieved)
        if themes:
            return _sanitize_answer_text(
                f"מהמידע המקומי עולה כי ההחלטה מבוססת על איזון בין {themes}. "
                "בפועל בוחנים כמה חלופות ובוחרים בזו שמתאימה ביותר לדרישות המערכת, למגבלות המימוש ולשיקולי העלות והמורכבות."
            )
        return _sanitize_answer_text(
            "מהמידע המקומי עולה כי הבחירה נשענת על trade-off בין כמה פרמטרים מרכזיים, "
            "ובפועל נהוג לבחון מספר חלופות ולבחור בזו שמתאימה בצורה הטובה ביותר לדרישות המערכת."
        )

    topic_summary = _summarize_topics(retrieved)
    if topic_summary:
        return _sanitize_answer_text(
            f"מהמידע המקומי עולה כי התשובה נשענת בעיקר על {topic_summary}. "
            "בפועל נהוג לבחון את הדרישות, את ההקשר ההנדסי ואת מגבלות המערכת לפני קביעה."
        )

    return _sanitize_answer_text(
        "מהמידע המקומי עולה כיוון חלקי בלבד, ולכן נכון להישען על המקור המקומי הקרוב ביותר לפני החלטה."
    )


def _best_item_text(retrieved: list[dict]) -> str:
    for record in retrieved:
        item = record["item"]
        text = item.get("answer") or item.get("question") or ""
        cleaned = _sanitize_answer_text(text)
        if cleaned:
            return cleaned
    return ""


def _sanitize_answer_text(text: str) -> str:
    cleaned = " ".join((text or "").strip().split())
    cleaned = re.sub(r"\bQA-\d{4}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(item|dataset|record|entry)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bבפריט\b", "", cleaned)
    cleaned = re.sub(r"\bפריט\b", "", cleaned)
    cleaned = re.sub(r"\bמופיע(?:ה|ים)?\b[: ]*", "", cleaned)
    cleaned = re.sub(r"\bdataset item says\b[: ]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .;:-")
    return cleaned


def _first_sentence(text: str) -> str:
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return ""
    for separator in [".", "?", "!", "\n"]:
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0]
            break
    return cleaned.strip(" .;:-")


def _normalize_sentence_start(text: str) -> str:
    cleaned = (text or "").strip()
    prefixes = [
        "בקצרה:",
        "למה:",
        "צעד מעשי הבא:",
        "התשובה הקצרה היא",
        "המסקנה היא",
    ]
    for prefix in prefixes:
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix):].strip(" .;:-")
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def _is_general_engineering_question(question: str) -> bool:
    q = (question or "").lower()
    return any(token in q for token in [
        "כיצד", "איך", "ארכיטקט", "architecture", "trade", "rf", "receiver", "מקלט",
        "wideband", "broadband", "design", "תכן", "בחירה", "בוחרים",
    ])


def _collect_theme_terms(retrieved: list[dict]) -> str:
    joined = " ".join(
        _sanitize_answer_text(record["item"].get("answer") or record["item"].get("question") or "")
        for record in retrieved[:3]
    ).lower()
    ordered_terms = [
        ("רוחב פס", ["רוחב פס", "wideband", "bandwidth"]),
        ("רגישות", ["רגישות", "sensitivity"]),
        ("ליניאריות", ["ליניאריות", "linearity"]),
        ("latency", ["latency"]),
        ("עלות", ["עלות", "cost"]),
        ("משקל", ["משקל", "weight"]),
        ("צריכת הספק", ["power", "צריכת הספק"]),
        ("מורכבות מימוש", ["implementation", "מורכבות", "מימוש", "integration"]),
        ("דגימה ישירה", ["direct sampling", "direct rf"]),
        ("סופרהטרודין", ["superheterodyne", "heterodyne"]),
        ("חלוקת תחומים", ["band split", "split"]),
    ]
    found = []
    for label, variants in ordered_terms:
        if any(variant in joined for variant in variants):
            found.append(label)
    return ", ".join(found[:6])


def _summarize_engineering_direction(retrieved: list[dict]) -> str:
    themes = _collect_theme_terms(retrieved)
    if themes:
        return f"בדרך כלל בוחרים את החלופה שנותנת את האיזון הטוב ביותר בין {themes}"
    return "בדרך כלל בוחנים כמה חלופות ומעדיפים את זו שעומדת טוב יותר בדרישות המערכת"


def _summarize_topics(retrieved: list[dict]) -> str:
    labels = []
    for record in retrieved[:3]:
        item = record["item"]
        for key in ["topic", "category", "domain"]:
            value = _sanitize_answer_text((item.get(key) or "").strip())
            if not value:
                continue
            lowered = value.lower()
            if lowered not in [label.lower() for label in labels]:
                labels.append(value)
            break
    return ", ".join(labels[:3])


def _dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _is_critical_fact_question(question: str) -> bool:
    q = (question or "").lower()
    return any(token in q for token in [
        "גרסה", "version", "approved", "approval", "מאושר", "אישור",
        "status", "סטטוס", "ready", "pass", "fail", "נכשל", "עבר",
        "latency", "mtbf", "availability", "throughput", "result", "תוצאה",
    ])
