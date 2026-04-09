import re

from offline_ai_loader import load_knowledge_source
from offline_ai_policy import compose_response, evaluate_confidence
from offline_ai_retrieval import retrieve_items


MAX_RETRIEVED_ITEMS = 5
STRICT_REFUSAL_MODE = True

_GREETING_PATTERNS = [
    "שלום", "היי", "בוקר טוב", "צהריים טובים", "ערב טוב",
    "hi", "hello", "good morning", "good afternoon", "good evening",
]

_PROJECT_TOKENS = [
    "הפרויקט", "כרגע", "מוכן", "מוכנים", "חסר", "חסרים", "מה מצב",
    "סיכונים", "סיכון", "משפיעים", "מושפעים", "משימות", "milestone", "milestones",
    "דיונים", "לקחים", "defects", "hazards", "vv", "בדיקות", "cdr", "pdr", "srr",
    "readiness", "open issues", "open items", "ספק", "ספקים", "supplier", "vendor",
]

_GENERAL_TOKENS = [
    "כיצד", "איך", "architecture", "trade", "best practice", "בדרך כלל",
    "wideband", "rf", "ארכיטקט", "מקלט", "תכן",
]


def ask_offline_ai(question: str, project_context: dict | None = None) -> dict:
    normalized_question = (question or "").strip()
    project_context = project_context or {}

    if not normalized_question:
        response = {
            "answer": "אין לי מספיק מידע מקומי כדי לקבוע.\nלמה: לא התקבלה שאלה לניתוח.\nצעד מעשי הבא: לנסח שאלה אחת ברורה וממוקדת.",
            "confidence": "low",
            "used_items": [],
            "missing_information": ["לא התקבלה שאלה"],
            "recommended_action": "לנסח שאלה אחת ברורה וממוקדת.",
            "refusal": True,
        }
        response["_debug"] = _build_intent_debug(
            normalized_question, "single", None, 1, {
                "question": normalized_question,
                "used_items": [],
                "contradiction": False,
                "is_critical_fact_question": False,
                "coverage_strength": 0.0,
                "decision_path": "empty_question_refusal",
                "final_confidence": "low",
                "final_refusal": True,
                "question_type": "general",
                "project_context_used": False,
                "project_evidence_count": 0,
                "kb_evidence_count": 0,
                "decision_source": "hard_case_refusal",
            }
        )
        return response

    intent = classify_intent(normalized_question)
    if intent["type"] == "greeting":
        response = {
            "answer": "שלום 👋\nאיך אפשר לעזור? אפשר לשאול על הפרויקט או על נושא הנדסי.",
            "confidence": "high",
            "used_items": [],
            "missing_information": [],
            "recommended_action": "לשאול שאלה אחת על הפרויקט או על נושא הנדסי.",
            "refusal": False,
        }
        response["_debug"] = _build_intent_debug(
            normalized_question, intent["type"], intent["subtype"], 1, {
                "question": normalized_question,
                "used_items": [],
                "contradiction": False,
                "is_critical_fact_question": False,
                "coverage_strength": 0.0,
                "decision_path": "greeting_short_circuit",
                "final_confidence": "high",
                "final_refusal": False,
                "question_type": "general",
                "project_context_used": False,
                "project_evidence_count": 0,
                "kb_evidence_count": 0,
                "decision_source": "intent_greeting",
            }
        )
        return response

    if intent["type"] == "nonsense":
        response = {
            "answer": "לא הצלחתי להבין את השאלה.\nאפשר לנסח מחדש או לשאול שאלה הנדסית/פרויקטלית?",
            "confidence": "medium",
            "used_items": [],
            "missing_information": [],
            "recommended_action": "לנסח את השאלה מחדש במשפט קצר וברור.",
            "refusal": False,
        }
        response["_debug"] = _build_intent_debug(
            normalized_question, intent["type"], intent["subtype"], 1, {
                "question": normalized_question,
                "used_items": [],
                "contradiction": False,
                "is_critical_fact_question": False,
                "coverage_strength": 0.0,
                "decision_path": "nonsense_short_circuit",
                "final_confidence": "medium",
                "final_refusal": False,
                "question_type": "general",
                "project_context_used": False,
                "project_evidence_count": 0,
                "kb_evidence_count": 0,
                "decision_source": "intent_nonsense",
            }
        )
        return response

    if intent["type"] == "multi":
        sub_questions = split_multi_question(normalized_question)
        sub_responses = []
        any_refusal = False
        used_items = []
        missing_information = []
        recommended_actions = []
        max_confidence = "low"
        aggregated_debug = {
            "question": normalized_question,
            "used_items": [],
            "contradiction": False,
            "is_critical_fact_question": False,
            "coverage_strength": 0.0,
            "decision_path": "multi_question_split",
            "final_confidence": "low",
            "final_refusal": False,
            "question_type": "mixed",
            "project_context_used": False,
            "project_evidence_count": 0,
            "kb_evidence_count": 0,
            "decision_source": "mixed",
        }
        for sub_question in sub_questions:
            sub_response = _answer_single_question(sub_question, project_context)
            sub_debug = sub_response.pop("_debug", {})
            sub_responses.append(f"שאלה: {sub_question}\nתשובה: {sub_response.get('answer','')}")
            any_refusal = any_refusal or bool(sub_response.get("refusal"))
            used_items.extend(sub_response.get("used_items") or [])
            missing_information.extend(sub_response.get("missing_information") or [])
            if sub_response.get("recommended_action"):
                recommended_actions.append(sub_response.get("recommended_action"))
            max_confidence = _max_confidence(max_confidence, sub_response.get("confidence") or "low")
            aggregated_debug["project_context_used"] = aggregated_debug["project_context_used"] or bool(sub_debug.get("project_context_used"))
            aggregated_debug["project_evidence_count"] += int(sub_debug.get("project_evidence_count") or 0)
            aggregated_debug["kb_evidence_count"] += int(sub_debug.get("kb_evidence_count") or 0)
            if sub_debug.get("decision_source") == "project_context":
                aggregated_debug["decision_source"] = "project_context"
            elif aggregated_debug["decision_source"] != "project_context" and sub_debug.get("decision_source"):
                aggregated_debug["decision_source"] = sub_debug.get("decision_source")
        response = {
            "answer": "\n\n".join(sub_responses),
            "confidence": max_confidence,
            "used_items": _dedupe(used_items),
            "missing_information": _dedupe(missing_information),
            "recommended_action": recommended_actions[0] if recommended_actions else "להמשיך עם כל תת-שאלה בנפרד לפי הסדר.",
            "refusal": any_refusal,
        }
        response["_debug"] = _build_intent_debug(
            normalized_question, intent["type"], intent["subtype"], len(sub_questions), aggregated_debug
        )
        return response

    response = _answer_single_question(normalized_question, project_context)
    response["_debug"] = _build_intent_debug(
        normalized_question, intent["type"], intent["subtype"], 1, response.get("_debug", {})
    )
    return response


def classify_intent(question: str) -> dict:
    text = (question or "").strip()
    normalized = _normalize_for_intent(text)
    if _is_greeting_only(normalized):
        return {"type": "greeting", "subtype": None, "confidence": "high"}
    if _is_nonsense(normalized):
        return {"type": "nonsense", "subtype": None, "confidence": "high"}
    if _is_multi_question(normalized):
        return {"type": "multi", "subtype": _classify_question_mode(normalized), "confidence": "medium"}
    return {"type": "single", "subtype": _classify_question_mode(normalized), "confidence": "high"}


def split_multi_question(question: str) -> list[str]:
    text = (question or "").strip()
    normalized = re.sub(r"\s+", " ", text)
    parts = re.split(r"\?\s*|\.\s+|!\s+|(?:\s\u05D5\u05D2\u05DD\s)|(?:\sand\s)|(?:\salso\s)", normalized)
    out = []
    for part in parts:
        cleaned = part.strip(" .?!,;:-")
        cleaned = re.sub(r"^(?:\u05D5\u05D2\u05DD|\u05D5|and also|also|and)\b[\s,;:-]*", "", cleaned, flags=re.IGNORECASE).strip(" .?!,;:-")
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out or [text]


def _answer_single_question(question: str, project_context: dict | None = None) -> dict:
    normalized_question = (question or "").strip()
    project_context = project_context or {}
    question_type = _classify_question_mode(normalized_question)
    ctx = _normalize_project_context(project_context)

    if question_type == "project_specific":
        project_response, project_evidence_count = _answer_from_project_context(normalized_question, ctx)
        project_response["_debug"] = {
            "question": normalized_question,
            "used_items": project_response.get("used_items", []),
            "contradiction": False,
            "is_critical_fact_question": True,
            "coverage_strength": 1.0 if project_evidence_count > 0 else 0.0,
            "decision_path": "project_context_answer" if not project_response.get("refusal") else "project_context_refusal",
            "final_confidence": project_response.get("confidence"),
            "final_refusal": project_response.get("refusal"),
            "question_type": question_type,
            "project_context_used": project_evidence_count > 0,
            "project_evidence_count": project_evidence_count,
            "kb_evidence_count": 0,
            "decision_source": "project_context" if project_evidence_count > 0 else "hard_case_refusal",
        }
        return project_response

    knowledge_source = load_knowledge_source()
    retrieved = retrieve_items(normalized_question, knowledge_source["items"], top_n=MAX_RETRIEVED_ITEMS)
    confidence, refusal, missing_information, recommended_action, debug = evaluate_confidence(
        normalized_question,
        retrieved,
        strict_refusal=STRICT_REFUSAL_MODE,
    )
    response = compose_response(
        question=normalized_question,
        retrieved=retrieved,
        confidence=confidence,
        refusal=refusal,
        missing_information=missing_information,
        recommended_action=recommended_action,
    )
    response["_debug"] = {
        "question": normalized_question,
        "used_items": [record["item"]["id"] for record in retrieved[:3] if record["item"].get("id")],
        "contradiction": debug.get("contradiction"),
        "is_critical_fact_question": debug.get("is_critical_fact_question"),
        "coverage_strength": debug.get("coverage_strength"),
        "decision_path": debug.get("decision_path"),
        "final_confidence": response.get("confidence"),
        "final_refusal": response.get("refusal"),
        "question_type": question_type,
        "project_context_used": False,
        "project_evidence_count": 0,
        "kb_evidence_count": len(retrieved),
        "decision_source": "generic_kb",
    }
    return response


def _build_intent_debug(question: str, intent_type: str, intent_subtype: str | None, sub_question_count: int, base_debug: dict) -> dict:
    debug = dict(base_debug or {})
    debug["question"] = question
    debug["intent_type"] = intent_type
    debug["intent_subtype"] = intent_subtype
    debug["is_multi"] = intent_type == "multi"
    debug["sub_question_count"] = sub_question_count
    return debug


def _normalize_for_intent(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_greeting_only(text: str) -> bool:
    stripped = re.sub(r"[!?,.]", "", text).strip()
    return stripped in _GREETING_PATTERNS


def _is_nonsense(text: str) -> bool:
    if not text:
        return False
    hebrew_words = re.findall(r"[\u0590-\u05FF]{2,}", text)
    english_words = re.findall(r"[a-zA-Z]{2,}", text)
    if hebrew_words:
        if re.search(r"(.)\1\1", text):
            return True
        return False
    if english_words:
        if len(english_words) == 1 and english_words[0] in _GREETING_PATTERNS:
            return False
        # Treat obvious keyboard mash / transliterated gibberish as nonsense:
        # low-vowel Latin tokens, repeated consonant-heavy words, and no known intent words.
        known_words = {
            "hi", "hello", "good", "morning", "afternoon", "evening",
            "project", "risk", "risks", "software", "system", "test", "tests",
            "cdr", "pdr", "srr", "architecture", "design", "rf", "receiver",
            "status", "milestone", "milestones", "task", "tasks", "supplier", "vendor",
            "how", "what", "when", "is", "are", "ready", "missing", "issue", "issues"
        }
        normalized_words = [word.lower() for word in english_words]
        if not any(word in known_words for word in normalized_words):
            vowel_light = 0
            for word in normalized_words:
                vowels = len(re.findall(r"[aeiou]", word))
                if len(word) >= 5 and vowels <= 1:
                    vowel_light += 1
            if vowel_light >= max(1, len(normalized_words) - 0):
                return True
            consonant_heavy = 0
            for word in normalized_words:
                if len(word) >= 5 and len(re.findall(r"[bcdfghjklmnpqrstvwxyz]", word)) >= len(word) - 1:
                    consonant_heavy += 1
            if consonant_heavy >= max(1, len(normalized_words)):
                return True
        if re.search(r"(.)\1\1", text):
            return True
        return False
    return True


def _is_multi_question(text: str) -> bool:
    if text.count("?") >= 2:
        return True
    if any(connector in text for connector in [" וגם ", " and ", " also "]):
        parts = split_multi_question(text)
        return len(parts) > 1
    question_phrases = re.split(r"[?.!]", text)
    question_like_count = 0
    for phrase in question_phrases:
        phrase = phrase.strip()
        if not phrase:
            continue
        if any(token in phrase for token in ["מה", "איך", "כיצד", "האם", "what", "how", "is ", "are "]):
            question_like_count += 1
    return question_like_count > 1


def _classify_question_mode(question: str) -> str:
    q = (question or "").lower()
    if any(token in q for token in _PROJECT_TOKENS):
        return "project_specific"
    if any(token in q for token in _GENERAL_TOKENS):
        return "general"
    return "general"


def _normalize_project_context(project_context: dict) -> dict:
    return {
        "project_id": project_context.get("projectId") or project_context.get("project_id") or "",
        "project_name": project_context.get("projectName") or project_context.get("project_name") or "",
        "domain": project_context.get("domain") or project_context.get("project", {}).get("domain") or "",
        "project": project_context.get("project") or {},
        "risks": project_context.get("risks") or [],
        "tasks": project_context.get("tasks") or [],
        "milestones": project_context.get("milestones") or [],
        "discussions": project_context.get("discussions") or [],
        "lessons": project_context.get("lessons") or [],
        "sysReqs": project_context.get("sysReqs") or [],
        "swReqs": project_context.get("swReqs") or [],
        "vv": project_context.get("vv") or [],
        "defects": project_context.get("defects") or [],
        "hazards": project_context.get("hazards") or [],
    }


def _answer_from_project_context(question: str, ctx: dict) -> tuple[dict, int]:
    q = (question or "").lower()
    if not ctx.get("project_id") and not ctx.get("project_name"):
        return _project_refusal(
            "אין לי מספיק מידע פרויקטלי מקומי כדי לקבוע.",
            "לא הועבר הקשר של הפרויקט הפעיל.",
            []
        ), 0

    evidence = _collect_project_evidence(q, ctx)
    evidence_count = sum(len(group) for group in evidence.values())

    if evidence_count == 0:
        return _project_refusal(
            "אין לי מספיק מידע פרויקטלי מקומי כדי לקבוע.",
            "לא נמצאו בפרויקט ראיות מקומיות רלוונטיות לשאלה שנשאלה.",
            ["סיכונים/משימות/דיונים/בדיקות רלוונטיים בפרויקט"]
        ), 0

    if _is_supplier_risk_question(q):
        return _build_supplier_risk_answer(evidence), evidence_count
    if _is_software_risk_question(q):
        return _build_software_risk_answer(evidence), evidence_count
    if _is_cdr_question(q):
        return _build_cdr_answer(evidence), evidence_count
    if _is_missing_status_question(q):
        return _build_missing_items_answer(ctx), evidence_count
    return _build_generic_project_answer(evidence), evidence_count


def _collect_project_evidence(question: str, ctx: dict) -> dict:
    evidence = {
        "risks": [],
        "tasks": [],
        "milestones": [],
        "discussions": [],
        "lessons": [],
        "sysReqs": [],
        "swReqs": [],
        "vv": [],
        "defects": [],
        "hazards": [],
    }
    intent_tokens = _derive_intent_tokens(question)
    for key in evidence.keys():
        for item in ctx.get(key, []):
            text = _flatten_item(item).lower()
            if _item_matches_intent(text, intent_tokens, question, key):
                evidence[key].append(item)
    return evidence


def _derive_intent_tokens(question: str) -> list[str]:
    q = (question or "").lower()
    tokens = []
    if any(token in q for token in ["תוכנה", "software", "sw", "firmware", "code"]):
        tokens += ["תוכנה", "software", "sw", "firmware", "bug", "defect", "code"]
    if any(token in q for token in ["ספק", "ספקים", "supplier", "vendor", "subcontract"]):
        tokens += ["ספק", "supplier", "vendor", "subcontract", "procurement", "lead time"]
    if "cdr" in q:
        tokens += ["cdr", "review", "open", "risk", "task", "ready", "readiness"]
    if any(token in q for token in ["סיכונים", "סיכון", "risk", "risks"]):
        tokens += ["risk", "סיכון", "סיכונים", "hazard", "issue", "defect"]
    if any(token in q for token in ["חסר", "חסרים", "open issues", "missing"]):
        tokens += ["open", "missing", "חסר", "pending", "todo", "blocked"]
    return list(dict.fromkeys(tokens))


def _item_matches_intent(text: str, tokens: list[str], question: str, key: str) -> bool:
    if not text:
        return False
    if _is_cdr_question(question) and key in ["tasks", "risks", "milestones", "defects", "vv", "discussions"]:
        return True
    if _is_missing_status_question(question) and key in ["tasks", "risks", "milestones", "vv", "discussions", "lessons", "defects"]:
        return True
    if not tokens:
        return False
    return any(token in text for token in tokens)


def _build_software_risk_answer(evidence: dict) -> dict:
    risk_count = len(evidence["risks"])
    defect_count = len(evidence["defects"])
    hazard_count = len(evidence["hazards"])
    parts = []
    if risk_count:
        parts.append(f"יש {risk_count} סיכונים רלוונטיים לתוכנה או ל-firmware")
    if defect_count:
        parts.append(f"יש {defect_count} defects פתוחים שמשפיעים על התוכנה")
    if hazard_count:
        parts.append(f"יש {hazard_count} hazards שיש להם השפעה תוכנתית")
    next_step = "לרכז את סיכוני התוכנה, ה-defects וה-hazards הרלוונטיים לרשימת מעקב אחת לפני החלטת המשך."
    return {
        "answer": "בקצרה: קיימים בפרויקט סיכונים שמשפיעים על התוכנה.\nלמה: מהמידע הפרויקטלי עולה כי " + ", ובנוסף ".join(parts) + ".\nצעד מעשי הבא: " + next_step,
        "confidence": "medium",
        "used_items": [],
        "missing_information": [],
        "recommended_action": next_step,
        "refusal": False,
    }


def _build_supplier_risk_answer(evidence: dict) -> dict:
    counts = []
    for key in ["risks", "tasks", "discussions", "lessons"]:
        if evidence[key]:
            counts.append(f"{len(evidence[key])} פריטי {_label_for_group(key)}")
    next_step = "לרכז את הסיכונים המושפעים מספקים, תלותי הרכש וה-open items מול הספקים לרשימת מעקב אחת."
    return {
        "answer": "בקצרה: קיימים בפרויקט סיכונים שמושפעים מספקים או מתלות חיצונית.\nלמה: מהמידע הפרויקטלי עולה כי זוהו " + ", ".join(counts) + " עם הקשר של ספקים, vendor או תלות חיצונית.\nצעד מעשי הבא: " + next_step,
        "confidence": "medium",
        "used_items": [],
        "missing_information": [],
        "recommended_action": next_step,
        "refusal": False,
    }


def _build_cdr_answer(evidence: dict) -> dict:
    open_tasks = len([t for t in evidence["tasks"] if str(t.get("status") or "").lower() not in ["done", "closed", "סגור", "הושלם"]])
    open_risks = len([r for r in evidence["risks"] if str(r.get("status") or "").lower() not in ["closed", "סגור"]])
    open_defects = len([d for d in evidence["defects"] if str(d.get("status") or "").lower() not in ["closed", "סגור"]])
    cdr_milestones = evidence["milestones"]
    parts = []
    if open_tasks:
        parts.append(f"יש {open_tasks} משימות פתוחות")
    if open_risks:
        parts.append(f"יש {open_risks} סיכונים פתוחים")
    if open_defects:
        parts.append(f"יש {open_defects} defects פתוחים")
    if cdr_milestones:
        parts.append("קיים milestone רלוונטי ל-CDR שצריך לבדוק את סטטוסו")
    else:
        parts.append("לא זוהה milestone מפורש של CDR")
    next_step = "לסגור את ה-open items הקריטיים ולעבור על רשימת הכניסה ל-CDR מול הנתונים המקומיים המעודכנים."
    return {
        "answer": "בקצרה: לפי הנתונים המקומיים אי אפשר עדיין להניח אוטומטית שהפרויקט מוכן ל-CDR.\nלמה: מהמידע הפרויקטלי עולה כי " + ", ".join(parts) + ".\nצעד מעשי הבא: " + next_step,
        "confidence": "medium",
        "used_items": [],
        "missing_information": [],
        "recommended_action": next_step,
        "refusal": False,
    }


def _build_missing_items_answer(ctx: dict) -> dict:
    missing = []
    if not ctx.get("tasks"):
        missing.append("אין נתוני משימות מעודכנים")
    if not ctx.get("risks"):
        missing.append("אין רשימת סיכונים פעילה")
    if not ctx.get("milestones"):
        missing.append("אין milestones מעודכנים")
    if not ctx.get("vv"):
        missing.append("אין כיסוי V&V זמין")
    if missing:
        return _project_refusal(
            "אין לי מספיק מידע פרויקטלי מקומי כדי לקבוע.",
            "; ".join(missing),
            missing
        )
    next_step = "לבדוק את הפריטים הפתוחים במשימות, בסיכונים וב-milestones כדי לגזור מה חסר כרגע בפרויקט."
    return {
        "answer": "בקצרה: יש בפרויקט מידע מקומי שמאפשר לזהות מה חסר כרגע, אבל צריך להישען על הפריטים הפתוחים בפועל.\nלמה: מהמידע הפרויקטלי עולה שקיימים נתוני משימות, סיכונים, milestones ובדיקות שמאפשרים תמונת מצב עדכנית.\nצעד מעשי הבא: " + next_step,
        "confidence": "medium",
        "used_items": [],
        "missing_information": [],
        "recommended_action": next_step,
        "refusal": False,
    }


def _build_generic_project_answer(evidence: dict) -> dict:
    groups = [f"{len(items)} {_label_for_group(name)}" for name, items in evidence.items() if items]
    next_step = "לחדד את השאלה לפריט פרויקטלי מסוים כמו סיכונים, משימות, CDR readiness או בדיקות."
    return {
        "answer": "בקצרה: יש בפרויקט מידע מקומי רלוונטי לשאלה, ולכן עדיף להישען עליו לפני שימוש בידע כללי.\nלמה: מהמידע הפרויקטלי עולה שנמצאו " + ", ".join(groups[:4]) + " שקשורים לשאלה שנשאלה.\nצעד מעשי הבא: " + next_step,
        "confidence": "medium",
        "used_items": [],
        "missing_information": [],
        "recommended_action": next_step,
        "refusal": False,
    }


def _flatten_item(item) -> str:
    if isinstance(item, dict):
        return " ".join(str(value or "") for value in item.values())
    return str(item or "")


def _label_for_group(name: str) -> str:
    return {
        "risks": "סיכונים",
        "tasks": "משימות",
        "milestones": "milestones",
        "discussions": "דיונים",
        "lessons": "לקחים",
        "sysReqs": "דרישות מערכת",
        "swReqs": "דרישות תוכנה",
        "vv": "פריטי V&V",
        "defects": "defects",
        "hazards": "hazards",
    }.get(name, name)


def _is_software_risk_question(q: str) -> bool:
    return ("סיכונ" in q or "risk" in q) and any(token in q for token in ["תוכנה", "software", "sw", "firmware"])


def _is_supplier_risk_question(q: str) -> bool:
    return ("סיכונ" in q or "risk" in q) and any(token in q for token in ["ספק", "ספקים", "supplier", "vendor", "subcontract"])


def _is_cdr_question(q: str) -> bool:
    return "cdr" in q or ("מוכן" in q and "cdr" in q)


def _is_missing_status_question(q: str) -> bool:
    return any(token in q for token in ["מה חסר", "חסר כרגע", "open issues", "missing", "מה מצב"])


def _project_refusal(conclusion: str, reason: str, missing: list[str]) -> dict:
    next_step = "להשלים או לעדכן את נתוני הפרויקט הרלוונטיים לפני קביעה."
    return {
        "answer": conclusion + "\nלמה: " + reason + "\nצעד מעשי הבא: " + next_step,
        "confidence": "low",
        "used_items": [],
        "missing_information": missing,
        "recommended_action": next_step,
        "refusal": True,
    }


def _dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _max_confidence(current: str, new_value: str) -> str:
    rank = {"low": 1, "medium": 2, "high": 3}
    return new_value if rank.get(new_value, 1) > rank.get(current, 1) else current
