import json
import re


_WEAK_WORDS = [
    "fast",
    "robust",
    "user-friendly",
    "friendly",
    "efficient",
    "reliable",
    "secure",
    "quick",
    "good",
    "easy",
    "simple",
    "גמיש",
    "מהיר",
    "אמין",
    "ידידותי",
    "טוב",
    "חזק",
    "יציב",
    "יעיל",
]


def analyze_requirement(project_context: dict | None, user_input: str | None) -> dict:
    text = (user_input or "").strip()
    req_type = _detect_requirement_type(text, project_context or {})
    quality_issues = _detect_requirement_quality_issues(text)
    improved = _improve_requirement_text(text, req_type)
    verification = _suggest_verification_method(improved)
    result = {
        "requirement": text,
        "type": req_type,
        "quality_issues": quality_issues,
        "improved_version": improved,
        "verification_method": verification,
    }
    result["_debug"] = _build_debug("requirements", text, result, project_context, ["sysReqs", "swReqs", "vv"])
    return result


def analyze_risk(project_context: dict | None, user_input: str | None) -> dict:
    text = (user_input or "").strip()
    category = _classify_risk_category(text)
    cause, effect = _extract_risk_cause_effect(text)
    severity = _score_risk_severity(text)
    probability = _score_risk_probability(text)
    mitigation = _suggest_risk_mitigation(category, text)
    owner = _suggest_risk_owner(category, project_context or {})
    result = {
        "risk_statement": _normalize_risk_statement(text, cause, effect),
        "category": category,
        "cause": cause,
        "effect": effect,
        "severity": severity,
        "probability": probability,
        "mitigation": mitigation,
        "owner_suggestion": owner,
    }
    result["_debug"] = _build_debug("risks", text, result, project_context, ["risks", "tasks", "hazards"])
    return result


def analyze_architecture(project_context: dict | None, user_input: str | None) -> dict:
    text = (user_input or "").strip()
    normalized = _norm(text)
    alternatives = _build_architecture_alternatives(normalized)
    recommended = _recommend_architecture(alternatives, normalized, project_context or {})
    missing_aspects = _detect_missing_architecture_aspects(text, project_context or {})
    result = {
        "alternatives": alternatives,
        "recommended": recommended,
        "missing_aspects": missing_aspects,
    }
    result["_debug"] = _build_debug("architecture", text, result, project_context, ["arch", "swArch", "icd", "risks"])
    return result


def analyze_review_readiness(project_context: dict | None) -> dict:
    ctx = project_context or {}
    reqs = list(ctx.get("sysReqs") or []) + list(ctx.get("swReqs") or [])
    vv = list(ctx.get("vv") or [])
    risks = list(ctx.get("risks") or [])
    defects = list(ctx.get("defects") or [])
    hazards = list(ctx.get("hazards") or [])
    milestones = list(ctx.get("milestones") or [])

    open_high_risks = [r for r in risks if _risk_rpn(r) >= 9 and str(r.get("status", "")).lower() != "closed"]
    open_defects = [d for d in defects if str(d.get("status", "")).lower() not in ("closed", "resolved", "done")]
    open_hazards = [h for h in hazards if str(h.get("status", "")).lower() not in ("closed", "accepted", "mitigated")]
    uncovered_reqs = _find_uncovered_requirements(reqs, vv)
    overdue = _find_overdue_milestones(milestones)

    gaps = []
    critical_items = []
    next_actions = []

    if not reqs:
        gaps.append("חסרה מסת דרישות בסיסית לבחינת בשלות הנדסית.")
    if uncovered_reqs:
        gaps.append(f"{len(uncovered_reqs)} דרישות עדיין ללא כיסוי V&V.")
        next_actions.append("להשלים קישור V&V לכל הדרישות הפתוחות לפני ביקורת התכן.")
    if open_high_risks:
        gaps.append(f"{len(open_high_risks)} סיכונים גבוהים עדיין פתוחים.")
        critical_items.append("יש סיכונים פתוחים ברמת חומרה/הסתברות גבוהה.")
        next_actions.append("לסגור תכנית mitigation ובעלות לכל הסיכונים הגבוהים.")
    if open_defects:
        gaps.append(f"{len(open_defects)} defects פתוחים.")
        critical_items.append("קיימים defects פתוחים שעלולים לפגוע בבשלות הביקורת.")
        next_actions.append("לרכז triage ל-defects פתוחים ולהגדיר תכנית סגירה.")
    if open_hazards:
        gaps.append(f"{len(open_hazards)} hazards פתוחים.")
        critical_items.append("קיימות סכנות בטיחות פתוחות ללא סגירה מלאה.")
        next_actions.append("להשלים סטטוס mitigation והחלטות בטיחות לפני Review.")
    if overdue:
        gaps.append(f"{len(overdue)} milestones באיחור.")
        next_actions.append("לעדכן תאריכי יעד ופעולות recovery למילסטונים באיחור.")
    if not milestones:
        gaps.append("לא הוגדרו milestones לביקורות המרכזיות.")
        next_actions.append("להגדיר milestone ותכולת checklist ל-PDR/CDR.")

    if critical_items or len(gaps) >= 4:
        status = "not_ready"
    elif gaps:
        status = "partial"
    else:
        status = "ready"
        next_actions.append("לבצע final review קצר על כיסוי, סיכונים ו-defects לפני הדיון.")

    result = {
        "status": status,
        "gaps": gaps,
        "critical_items": critical_items,
        "next_actions": _dedupe(next_actions),
    }
    result["_debug"] = _build_debug("review-readiness", "", result, project_context, ["risks", "sysReqs", "swReqs", "vv", "defects", "hazards", "milestones"])
    return result


def _build_debug(action_type: str, user_input: str, result: dict, project_context: dict | None, relevant_keys: list[str]) -> dict:
    ctx = project_context or {}
    used = 0
    for key in relevant_keys:
        value = ctx.get(key) or []
        if isinstance(value, list):
            used += len(value)
        elif value:
            used += 1
    return {
        "action_type": action_type,
        "input_size": len((user_input or "").strip()),
        "output_size": len(json.dumps({k: v for k, v in result.items() if k != "_debug"}, ensure_ascii=False)),
        "project_items_used": used,
    }


def _detect_requirement_type(text: str, project_context: dict) -> str:
    normalized = _norm(text)
    if any(token in normalized for token in ["software", "firmware", "code", "api", "algorithm", "תוכנה"]):
        return "software"
    if any(token in normalized for token in ["mechanical", "mount", "housing", "thermal", "מכאנ", "מבנה"]):
        return "mechanical"
    if any(token in normalized for token in ["interface", "protocol", "bus", "icd", "ממשק"]):
        return "interface"
    if any(token in normalized for token in ["safety", "hazard", "fail-safe", "בטיחות"]):
        return "safety"
    if any(str(req.get("domain", "")).lower().startswith("sw") for req in project_context.get("swReqs") or []):
        return "software"
    return "system"


def _detect_requirement_quality_issues(text: str) -> list[str]:
    issues = []
    normalized = _norm(text)
    if not text.strip():
        return ["נדרש טקסט דרישה כדי לבצע שיפור."]
    if "shall" not in normalized and "must" not in normalized and "will" not in normalized and " י" not in normalized:
        issues.append("הדרישה אינה מנוסחת במבנה מחייב וברור.")
    if any(word in normalized for word in _WEAK_WORDS):
        issues.append("נמצא ניסוח חלש או לא מדיד.")
    if not re.search(r"\d", text) and not any(term in normalized for term in ["within", "less than", "at least", "under", "מקסימום", "לפחות", "בתוך"]):
        issues.append("חסר קריטריון מדיד או תנאי קבלה ברור.")
    if len(text.split()) < 5:
        issues.append("הדרישה קצרה מדי ועלולה להיות עמומה.")
    return issues


def _improve_requirement_text(text: str, req_type: str) -> str:
    base = (text or "").strip().rstrip(".")
    subject = {
        "software": "The software shall",
        "mechanical": "The mechanical design shall",
        "interface": "The interface shall",
        "safety": "The system shall",
        "system": "The system shall",
    }.get(req_type, "The system shall")
    if not base:
        return subject + " meet a clearly defined measurable requirement."
    cleaned = re.sub(r"^\s*(the system|the software|system|software|shall|must|should)\s+", "", base, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(should|must|will)\b", "shall", cleaned, flags=re.IGNORECASE)
    if not re.search(r"\d", cleaned):
        cleaned += " under defined operating conditions with measurable acceptance criteria"
    if not cleaned.lower().startswith(subject.lower().replace(" shall", "")):
        return subject + " " + cleaned[0].lower() + cleaned[1:] + "."
    return cleaned + "."


def _suggest_verification_method(text: str) -> str:
    normalized = _norm(text)
    if any(token in normalized for token in ["analysis", "latency", "mtbf", "throughput", "analysis", "חישוב", "ניתוח"]):
        return "analysis"
    if any(token in normalized for token in ["visual", "label", "drawing", "document", "inspection", "בדיקה ויזואלית", "מסמך"]):
        return "inspection"
    if any(token in normalized for token in ["operator", "display", "use", "demo", "demonstration", "הדגמה"]):
        return "demonstration"
    return "test"


def _classify_risk_category(text: str) -> str:
    normalized = _norm(text)
    if any(token in normalized for token in ["supplier", "vendor", "subcontractor", "ספק", "קבלן"]):
        return "supplier"
    if any(token in normalized for token in ["software", "firmware", "algorithm", "תוכנה"]):
        return "software"
    if any(token in normalized for token in ["schedule", "delay", "milestone", "לו\"ז", "איחור"]):
        return "schedule"
    if any(token in normalized for token in ["safety", "hazard", "בטיחות"]):
        return "safety"
    if any(token in normalized for token in ["interface", "icd", "integration", "ממשק", "אינטגרציה"]):
        return "integration"
    return "technical"


def _extract_risk_cause_effect(text: str) -> tuple[str, str]:
    cleaned = (text or "").strip().rstrip(".")
    cause = ""
    effect = ""
    if "עקב" in cleaned:
        parts = cleaned.split("עקב", 1)
        effect = parts[0].strip(" ,.-")
        cause = parts[1].strip(" ,.-")
    elif "בגלל" in cleaned:
        parts = cleaned.split("בגלל", 1)
        effect = parts[0].strip(" ,.-")
        cause = parts[1].strip(" ,.-")
    elif "may cause" in cleaned.lower():
        parts = re.split(r"may cause", cleaned, flags=re.IGNORECASE, maxsplit=1)
        cause = parts[0].strip(" ,.-")
        effect = parts[1].strip(" ,.-")
    elif "עלול" in cleaned:
        parts = cleaned.split("עלול", 1)
        cause = parts[0].strip(" ,.-")
        effect = parts[1].strip(" ,.-")
    return cause or "לא צוין גורם ישיר", effect or "לא צוין אפקט ישיר"


def _normalize_risk_statement(text: str, cause: str, effect: str) -> str:
    if text.strip():
        return text.strip().rstrip(".") + "."
    return f"קיים סיכון עקב {cause} שעלול לגרום ל-{effect}."


def _score_risk_severity(text: str) -> int:
    normalized = _norm(text)
    if any(token in normalized for token in ["critical", "catastrophic", "safety", "loss", "כשל חמור", "בטיחות"]):
        return 5
    if any(token in normalized for token in ["major", "delay", "integration", "high", "איחור", "משמעותי"]):
        return 4
    if any(token in normalized for token in ["moderate", "medium", "בינוני"]):
        return 3
    return 2


def _score_risk_probability(text: str) -> int:
    normalized = _norm(text)
    if any(token in normalized for token in ["likely", "frequent", "ongoing", "already", "קיים", "צפוי"]):
        return 4
    if any(token in normalized for token in ["possible", "may", "could", "אפשרי", "עלול"]):
        return 3
    return 2


def _suggest_risk_mitigation(category: str, text: str) -> str:
    if category == "supplier":
        return "לקבוע תכנית מעקב ספק, נקודות בקרה ותכנית חלופית לאספקה."
    if category == "software":
        return "להגדיר owner טכני, בדיקות כיסוי, ו-closure criteria לבעיה."
    if category == "schedule":
        return "לפרק למשימות recovery קצרות ולעדכן milestone מוסכם."
    if category == "safety":
        return "להשלים hazard analysis, mitigation מאושרת וסטטוס אימות."
    if category == "integration":
        return "להגדיר ICD מעודכן, owner משותף ובדיקת אינטגרציה מוקדמת."
    return "להגדיר פעולת mitigation, owner ולו\"ז סגירה מדיד."


def _suggest_risk_owner(category: str, project_context: dict) -> str:
    owners = [str(r.get("owner", "")).strip() for r in project_context.get("risks") or [] if str(r.get("owner", "")).strip()]
    if owners:
        return owners[0]
    mapping = {
        "supplier": "PM / Supply Chain",
        "software": "SW Lead",
        "schedule": "PM",
        "safety": "Safety Lead",
        "integration": "System Engineer",
        "technical": "Technical Lead",
    }
    return mapping.get(category, "PM")


def _build_architecture_alternatives(normalized: str) -> list[dict]:
    if any(token in normalized for token in ["rf", "receiver", "wideband", "רדיו", "מקלט"]):
        return [
            {
                "name": "Direct Sampling",
                "description": "דגימה ישירה של התחום הרחב בשרשרת RF קצרה יחסית.",
                "pros": ["פישוט שרשרת RF", "גמישות עיבוד דיגיטלי", "פחות שלבי המרה"],
                "cons": ["עומס גבוה על ADC", "רגישות גבוהה ל-linearity ול-dynamic range"],
            },
            {
                "name": "Superheterodyne",
                "description": "המרה לתדר ביניים לפני דיגום ועיבוד.",
                "pros": ["שליטה טובה יותר בסינון", "התאמה גבוהה למקלטים תובעניים"],
                "cons": ["מורכבות חומרה גבוהה יותר", "כיול ואינטגרציה מסובכים יותר"],
            },
            {
                "name": "Band-Split Hybrid",
                "description": "פיצול התחום לכמה ערוצים או תתי-תחומים לפני דיגום.",
                "pros": ["איזון בין ביצועים למורכבות", "שליטה טובה יותר ברוחב פס אפקטיבי"],
                "cons": ["יותר רכיבים וממשקים", "מורכבות חלוקת תחום וסנכרון"],
            },
        ]
    return [
        {
            "name": "Centralized Architecture",
            "description": "ריכוז הלוגיקה המרכזית ברכיב ראשי אחד.",
            "pros": ["פשטות תפעולית", "traceability ברורה"],
            "cons": ["נקודת כשל מרכזית", "פחות גמישות להתרחבות"],
        },
        {
            "name": "Layered Modular Architecture",
            "description": "חלוקה לשכבות או מודולים עם ממשקים מוגדרים.",
            "pros": ["תחזוקה נוחה", "בעלות ברורה", "הרחבה פשוטה יותר"],
            "cons": ["מחיר אינטגרציה", "תלות ב-ICD ובבקרת תצורה"],
        },
        {
            "name": "Hybrid Distributed Architecture",
            "description": "פיצול פונקציות קריטיות לרכיבים ייעודיים עם תיאום מרכזי.",
            "pros": ["איזון בין ביצועים וגמישות", "הקטנת צווארי בקבוק"],
            "cons": ["מורכבות תזמון וממשקים", "נדרש תכנון data flow מוקפד"],
        },
    ]


def _recommend_architecture(alternatives: list[dict], normalized: str, project_context: dict) -> str:
    if any(token in normalized for token in ["latency", "low latency", "real-time", "זמן אמת", "שהיה נמוכה"]):
        return alternatives[0]["name"]
    if any(token in normalized for token in ["interface", "integration", "modular", "ממשק", "מודולרי"]):
        return alternatives[min(1, len(alternatives) - 1)]["name"]
    if len(project_context.get("risks") or []) > 8:
        return alternatives[min(1, len(alternatives) - 1)]["name"]
    return alternatives[0]["name"]


def _detect_missing_architecture_aspects(text: str, project_context: dict) -> list[str]:
    normalized = _norm(text + " " + json.dumps(project_context.get("project") or {}, ensure_ascii=False))
    aspects = []
    if not any(token in normalized for token in ["latency", "שהיה", "timing"]):
        aspects.append("latency / timing budget")
    if not any(token in normalized for token in ["interface", "api", "bus", "icd", "ממשק"]):
        aspects.append("interfaces / ICD definition")
    if not any(token in normalized for token in ["data flow", "pipeline", "stream", "זרימה", "data"]):
        aspects.append("data flow")
    if not any(token in normalized for token in ["owner", "responsibility", "אחראי", "בעלות"]):
        aspects.append("ownership / responsibility split")
    return aspects


def _find_uncovered_requirements(reqs: list, vv: list) -> list[dict]:
    covered = set()
    for item in vv:
        linked = item.get("linkedRequirementId") or item.get("rid") or item.get("reqId") or item.get("linkedRid")
        if linked:
            covered.add(str(linked))
    return [r for r in reqs if str(r.get("rid") or r.get("id") or "") not in covered]


def _find_overdue_milestones(milestones: list) -> list[dict]:
    overdue = []
    for m in milestones:
        due = str(m.get("date") or m.get("targetDate") or "").strip()
        status = str(m.get("status") or "").lower()
        if due and status not in ("done", "closed", "complete", "completed"):
            overdue.append(m)
    return overdue


def _risk_rpn(risk: dict) -> int:
    sev = int(risk.get("sev") or risk.get("severity") or 0)
    prob = int(risk.get("prob") or risk.get("probability") or 0)
    return sev * prob


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out
