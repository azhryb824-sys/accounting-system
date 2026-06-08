import re
from dataclasses import asdict, dataclass


STOP_WORDS = {
    "ما", "ماذا", "من", "هو", "هي", "هل", "عن", "في", "على", "إلى", "الى",
    "اشرح", "عرف", "تعريف", "يمكن", "اريد", "أريد", "the", "is", "of", "and",
}

DOMAIN_TERMS = {
    "accounting": (
        "محاسب", "المحاسبة", "خصوم", "أصول", "اصول", "قيد", "فاتورة", "ضريبة",
        "إيرادات", "ايرادات", "مصروفات", "مخزون", "تدفق نقدي", "ميزان",
    ),
    "mathematics": (
        "احسب", "معادلة", "اشتق", "تكامل", "رياضيات", "نسبة", "مجموع", "متوسط",
    ),
    "science": (
        "فيزياء", "كيمياء", "أحياء", "احياء", "فلك", "هندسة", "طاقة", "ذرة",
    ),
    "geography": (
        "عاصمة", "دولة", "مدينة", "تقع", "جغرافيا", "سكان", "مساحة", "قارة",
    ),
    "language": (
        "إعراب", "اعراب", "ترجم", "صياغة", "نحو", "لغة", "انجليزي", "إنجليزي",
    ),
    "business": (
        "مشروع", "دراسة جدوى", "سوق", "عملاء", "تسويق", "خطة عمل",
    ),
}

CURRENT_TERMS = (
    "اليوم", "الآن", "الان", "حاليا", "حالياً", "أحدث", "احدث", "آخر", "اخر",
    "سعر", "رئيس", "وزير", "قانون الحالي", "أخبار", "اخبار",
)


def normalize(text):
    text = re.sub(r"[^\w\s\u0600-\u06ff]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def tokens(text):
    return {
        token for token in re.findall(r"[\w\u0600-\u06ff]+", normalize(text))
        if len(token) > 2 and token not in STOP_WORDS
    }


@dataclass(frozen=True)
class QueryPlan:
    intent: str
    domain: str
    needs_web: bool
    needs_calculation: bool
    complexity: str
    language: str

    def to_dict(self):
        return asdict(self)


def plan_query(question):
    normalized = normalize(question)
    domain_scores = {
        domain: sum(1 for term in terms if term in normalized)
        for domain, terms in DOMAIN_TERMS.items()
    }
    domain = max(domain_scores, key=domain_scores.get)
    if not domain_scores[domain]:
        domain = "general"

    needs_calculation = domain == "mathematics" or bool(
        re.search(r"\d+\s*[-+*/%=]\s*\d+", normalized)
    )
    needs_web = any(term in normalized for term in CURRENT_TERMS) or any(
        term in normalized for term in ("ابحث", "الانترنت", "الإنترنت", "مصادر", "رابط")
    )
    if needs_calculation:
        intent = "calculate"
    elif any(term in normalized for term in ("قارن", "الفرق", "مقارنة")):
        intent = "compare"
    elif any(term in normalized for term in ("حلل", "قيّم", "قيم", "توصيات")):
        intent = "analyze"
    elif any(term in normalized for term in ("اكتب", "صغ", "صياغة", "ترجم")):
        intent = "create"
    elif any(term in normalized for term in ("ما هو", "ما هي", "ماهي", "عرف", "اشرح")):
        intent = "explain"
    else:
        intent = "answer"

    word_count = len(normalized.split())
    complexity = "high" if word_count >= 25 else "medium" if word_count >= 10 else "low"
    language = "ar" if any("\u0600" <= char <= "\u06ff" for char in question) else "en"
    return QueryPlan(intent, domain, needs_web, needs_calculation, complexity, language)


def resolve_followup(question, history):
    normalized = normalize(question)
    followup_terms = (
        "وماذا عنها", "وماذا عنه", "وما مساحتها", "وما مساحته", "وأين تقع",
        "واين تقع", "وكم عددها", "وما السبب", "وماذا بعد", "قارنها", "قارنه",
    )
    if len(normalized.split()) > 6 and not any(term in normalized for term in followup_terms):
        return question
    if not any(term in normalized for term in followup_terms):
        return question
    previous = [
        str(item.get("content", "")).strip()
        for item in history
        if str(item.get("role", "")).lower() == "user" and item.get("content")
    ]
    if not previous:
        return question
    subject = re.sub(
        r"^(?:حدثني عن|اشرح|عرّف|عرف|ما هو|ما هي)\s+",
        "",
        previous[-1][:500],
        flags=re.IGNORECASE,
    ).strip(" ؟?")
    rewrites = (
        (("وما مساحتها", "وما مساحته"), f"ما مساحة {subject}؟"),
        (("وأين تقع", "واين تقع"), f"أين تقع {subject}؟"),
        (("وكم عددها",), f"كم عدد {subject}؟"),
        (("وما السبب",), f"ما سبب {subject}؟"),
        (("قارنها", "قارنه"), f"قارن {subject} بالموضوع المذكور في السؤال الحالي."),
    )
    for phrases, rewritten in rewrites:
        if any(phrase in normalized for phrase in phrases):
            return rewritten
    return f"{question} المقصود هو: {subject}"


def assess_answer(question, answer, references=None):
    answer = (answer or "").strip()
    if not answer:
        return {"score": 0, "level": "low", "reason": "empty"}
    failure_phrases = (
        "لا أملك إجابة موثوقة", "تعذر تشغيل", "الخادم غير جاهز", "لم تتوفر إجابة",
    )
    if any(phrase in answer for phrase in failure_phrases):
        return {"score": 15, "level": "low", "reason": "fallback"}

    query_tokens = tokens(question)
    answer_tokens = tokens(answer)
    overlap = len(query_tokens & answer_tokens)
    coverage = overlap / max(1, min(len(query_tokens), 5))
    score = 45 + min(35, round(coverage * 35))
    if references:
        score += 10
    if len(answer) >= 80:
        score += 5
    score = min(100, score)
    level = "high" if score >= 75 else "medium" if score >= 50 else "low"
    return {"score": score, "level": level, "reason": "evaluated"}
