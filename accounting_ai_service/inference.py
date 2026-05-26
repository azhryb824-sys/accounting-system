import base64
import io
import json
import os
import re
import sys
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
except ImportError:
    Image = None
    ImageEnhance = None
    ImageFilter = None
    ImageOps = None

try:
    import pytesseract
except ImportError:
    pytesseract = None


MODEL_NAME = "نموذج عبدالرحمن المحاسبي"
MODEL_OWNER = "عبدالرحمن"
MODEL_PATH = Path(os.environ.get("ACCOUNTING_AI_MODEL_PATH") or Path(__file__).resolve().parent / "models" / "my_model")
AI_BACKEND = os.environ.get("ACCOUNTING_AI_BACKEND", "auto").strip().lower()
LOCAL_ANALYSIS_ONLY = os.environ.get("LOCAL_ANALYSIS_ONLY", "false").strip().lower() not in {"0", "false", "no", "off"}
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct").strip()
OPENAI_COMPATIBLE_API_KEY = os.environ.get("OPENAI_COMPATIBLE_API_KEY", "").strip()
OPENAI_COMPATIBLE_BASE_URL = os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
OPENAI_COMPATIBLE_MODEL = os.environ.get("OPENAI_COMPATIBLE_MODEL", "gpt-4o-mini").strip()
REQUIRE_HOSTED_AI = os.environ.get("REQUIRE_HOSTED_AI", "false").strip().lower() in {"1", "true", "yes", "on"}
REQUIRE_LOCAL_MODEL = os.environ.get("REQUIRE_LOCAL_MODEL", "false").strip().lower() in {"1", "true", "yes", "on"}
ENABLE_OPEN_WEB_SEARCH = (
    not LOCAL_ANALYSIS_ONLY
    and os.environ.get("ENABLE_OPEN_WEB_SEARCH", "true").strip().lower() not in {"0", "false", "no", "off"}
)
USER_MEMORY: list[str] = []


SPEECH_NORMALIZATION_REPLACEMENTS = {
    "إفتح": "افتح",
    "فتح لي": "افتح",
    "افتح لي": "افتح",
    "روح": "اذهب",
    "وريني": "اعرض",
    "ورني": "اعرض",
    "عايز": "أريد",
    "داير": "أريد",
    "ابغى": "أريد",
    "ابي": "أريد",
    "وش": "ما",
    "ايش": "ما",
    "إيش": "ما",
    "حل": "حلل",
    "حلّل": "حلل",
    "قيم": "قيّم",
    "قَيّم": "قيّم",
    "الفتره": "الفترة",
    "الشركه": "الشركة",
    "الفاتوره": "الفاتورة",
    "الضريبه": "الضريبة",
}


def normalize_user_question_text(question: str) -> str:
    text = re.sub(r"\s+", " ", (question or "")).strip()
    if not text:
        return ""
    for old, new in SPEECH_NORMALIZATION_REPLACEMENTS.items():
        text = re.sub(rf"(?<!\w){re.escape(old)}(?!\w)", new, text, flags=re.IGNORECASE)
    text = re.sub(r"[؟?]{2,}", "؟", text)
    return text.strip()


def _analyze_question(question: str) -> dict[str, Any]:
    normalized_text = normalize_user_question_text(_extract_user_question(question))
    normalized = normalized_text.lower()
    web_terms = (
        "ابحث", "بحث", "النت", "الانترنت", "الإنترنت", "مصادر", "رابط", "روابط",
        "أحدث", "احدث", "آخر", "اخر", "اليوم", "حاليا", "حالياً", "معلومة حديثة",
    )
    accounting_terms = (
        "حلل", "تحليل", "قيّم", "قيم", "تقرير", "مبيعات", "مشتريات", "مخزون",
        "فاتورة", "فواتير", "ربح", "خسارة", "رصيد", "ضريبة", "قيد",
    )
    explanation_terms = ("اشرح", "ما هو", "ما هي", "ما معنى", "لماذا", "عرف", "تعريف", "وضح")
    execution_terms = ("افتح", "اذهب", "اعرض", "أظهر", "انتقل", "نفذ", "أضف", "اضف", "أنشئ", "انشئ")
    return {
        "normalized_text": normalized_text,
        "asks_web": any(term in normalized for term in web_terms),
        "asks_accounting": any(term in normalized for term in accounting_terms),
        "needs_explanation": any(term in normalized for term in explanation_terms),
        "asks_execution": any(term in normalized for term in execution_terms),
    }


def _load_transformers_runtime():
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        return None, None, None
    return torch, AutoModelForCausalLM, AutoTokenizer

SYSTEM_PROMPT = f"""
أنت {MODEL_NAME}، مساعد ذكاء اصطناعي خاص بـ {MODEL_OWNER}.
تجيب بالعربية بوضوح وبنقاط متعددة عند الحاجة، وتركز على المحاسبة والفواتير والمخزون والقيود اليومية والرواتب والسلف.
إذا كانت البيانات غير كافية فاذكر ذلك بوضوح ولا تخترع أرقاما.
""".strip()

PRIVATE_KNOWLEDGE = {
    "الفاتورة الضريبية": "الفاتورة الضريبية مستند رسمي يوضح بيانات البائع والمشتري والسلع أو الخدمات والمبلغ وضريبة القيمة المضافة، وتستخدم لإثبات عملية البيع محاسبيا وضريبيا.",
    "المخزون عند البيع": "عند البيع تنخفض كمية الصنف من المخزون بمقدار الكمية المباعة، ويظهر أثر العملية في تكلفة البضاعة المباعة والإيراد حسب طريقة التسجيل المحاسبي.",
    "قيد اليومية": "قيد اليومية هو تسجيل محاسبي لكل عملية مالية، ويجب أن يحتوي على طرف مدين وطرف دائن بحيث يتساوى مجموع المدين مع مجموع الدائن.",
    "المصروفات": "المصروفات تقلل صافي الربح لأنها تمثل تكلفة تحملتها المنشأة للحصول على الإيراد أو تشغيل النشاط.",
    "الدفع النقدي": "الدفع النقدي يعني أن قيمة العملية تم تحصيلها مباشرة وقت البيع أو تقديم الخدمة، بدلا من تسجيلها كذمة على العميل.",
    "البيع الآجل": "البيع الآجل يعني بيع سلعة أو خدمة الآن مع تأجيل تحصيل المبلغ، ويظهر عادة ضمن حسابات العملاء أو الذمم المدينة.",
    "ضريبة القيمة المضافة": "ضريبة القيمة المضافة ضريبة غير مباشرة تظهر في المبيعات كضريبة مخرجات وفي المشتريات كضريبة مدخلات، ويحسب صافي الالتزام من الفرق بينهما.",
    "حد التنبيه": "حد التنبيه في المخزون هو مستوى تحدده للصنف حتى ينبهك النظام عند انخفاض الكمية، مما يساعد على إعادة الطلب في الوقت المناسب.",
    "من أنت": f"أنا {MODEL_NAME}، مساعد ذكاء اصطناعي محاسبي خاص بـ {MODEL_OWNER} ومصمم لمساعدتك في الفواتير والمخزون والقيود والرواتب والسلف.",
}

ACCOUNTING_PATTERNS = [
    (
        "الرواتب",
        ("راتب", "رواتب", "مسير", "موظف", "الموظفين"),
        "الرواتب تمر بمرحلتين: اعتماد الراتب ثم دفعه. عند الاعتماد يثبت مصروف الرواتب مقابل رواتب مستحقة، وإذا وُجد خصم سلفة يخفض حساب سلف الموظفين. عند الدفع تخفض الرواتب المستحقة مقابل الصندوق أو البنك.",
    ),
    (
        "السلف",
        ("سلفة", "سلف", "advance"),
        "سلفة الموظف تسجل كأصل على حساب سلف الموظفين عند صرفها. عند خصمها من الراتب ينخفض رصيد السلفة ويظهر الخصم ضمن قيد استحقاق الراتب حتى تصبح السلفة مسددة بالكامل.",
    ),
    (
        "فواتير البيع",
        ("فاتورة بيع", "مبيعات", "بيع", "عميل"),
        "فاتورة البيع تؤثر على الإيرادات وضريبة القيمة المضافة. إذا كانت نقدية أو بطاقة أو تحويل يكون الطرف المدين الصندوق أو البنك، وإذا كانت آجلة يكون الطرف المدين العملاء. كما ينخفض المخزون وتثبت تكلفة البضاعة المباعة عند الترحيل.",
    ),
    (
        "فواتير الشراء",
        ("فاتورة شراء", "مشتريات", "شراء", "مورد"),
        "فاتورة الشراء تزيد المخزون وتثبت ضريبة المدخلات، ويكون الطرف الدائن غالبا الموردين إذا لم يتم السداد مباشرة. يجب التأكد من عدم تكرار تحديث المخزون عند إدخال بنود الشراء.",
    ),
    (
        "القيود",
        ("قيد", "قيود", "مدين", "دائن"),
        "أي عملية محاسبية صحيحة يجب أن تنتج قيدا متوازنا: مجموع المدين يساوي مجموع الدائن. إذا لم يتوازن القيد فهناك خطأ في الحسابات أو في اختيار الحسابات المرتبطة بالعملية.",
    ),
    (
        "التقارير",
        ("تقرير", "تقارير", "تحليل", "مؤشرات"),
        "ابدأ بقراءة المبيعات والمشتريات وقيمة المخزون والرواتب والسلف المفتوحة. أهم التنبيهات تكون عند زيادة المشتريات عن المبيعات، ارتفاع السلف المفتوحة، انخفاض المخزون عن حد التنبيه، أو وجود عمليات غير مرحلة محاسبيا.",
    ),
]


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word.lower() in text for word in words)


GREETING_PATTERNS = (
    "السلام عليكم",
    "سلام عليكم",
    "مرحبا",
    "أهلا",
    "اهلا",
    "هلا",
    "صباح الخير",
    "مساء الخير",
    "حيّاك",
    "حياك",
    "hello",
    "hi",
)

GENERAL_CHAT_PATTERNS = [
    (
        ("كيف حالك", "كيفك", "كيف الحال", "عامل ايه", "عامل شنو", "اخبارك"),
        "أنا بخير وبحماس للعمل معك. جاهز أراجع الأرقام، أشرح لك أي مفهوم محاسبي، أو أساعدك خطوة بخطوة داخل النظام. أعطني السؤال وسأحاول أن أجعله واضحا ومفيدا بدون تعقيد.",
    ),
    (
        ("شكرا", "شكرًا", "يعطيك العافية", "الله يعطيك العافية", "ممتاز", "تمام"),
        "العفو، هذا من ذوقك. خلينا نكمل الشغل بهدوء: إذا عندك فاتورة، قيد، راتب، سلفة، أو سؤال محاسبي عام أرسله لي وسأرتبه لك بشكل واضح.",
    ),
    (
        ("من أنت", "مين انت", "من انت", "عرف نفسك", "ما دورك"),
        f"أنا {MODEL_NAME}، مساعد محاسبي ودود داخل النظام. أساعدك في فهم المحاسبة، قراءة مؤشرات شركتك، متابعة الفواتير والمخزون والرواتب والسلف، وتوجيهك للخطوة المناسبة داخل النظام.",
    ),
    (
        ("ماذا تستطيع", "وش تقدر", "ايش تقدر", "شنو بتقدر", "ساعدني"),
        "أقدر أساعدك في ثلاثة أشياء رئيسية: شرح المفاهيم المحاسبية بلغة بسيطة، قراءة أرقام شركتك المتاحة في النظام، وإرشادك لتنفيذ العمليات مثل الفواتير والقيود والرواتب والسلف. اسألني بطريقتك، وأنا أرتب الإجابة.",
    ),
    (
        ("نكتة", "اضحكني", "خلينا نضحك", "مرح"),
        "ابتسامة خفيفة قبل القيود: المحاسب لا يخاف من الدائن، يخاف فقط من قيد غير متوازن في آخر الدوام. الآن نرجع بجدية لطيفة: ما السؤال الذي تريد تحليله؟",
    ),
    (
        ("وداعا", "مع السلامة", "باي", "الى اللقاء"),
        "مع السلامة، سعدت بمساعدتك. عندما تعود، أرسل لي السؤال أو العملية المطلوبة وسأكمل معك من غير تعقيد.",
    ),
]

ACCOUNTING_CONCEPT_PATTERNS = [
    (
        ("وش يعني مدين", "وش يعني دائن", "ايش يعني مدين", "ايش يعني دائن"),
        "ببساطة: المدين هو الجهة اللي عليها تسجيل في الطرف المدين، والدائن هو الطرف المقابل. غالبا الأصول والمصروفات تزيد مدين، والإيرادات والالتزامات تزيد دائن. أهم شيء القيد لازم يتوازن: المدين = الدائن.",
    ),
    (
        ("شنو المدين", "شنو الدائن", "يعني شنو مدين", "يعني شنو دائن"),
        "بشرح بسيط: المدين والدائن هما طرفين القيد. الأصول والمصروفات غالبا بتزيد في المدين، والالتزامات والإيرادات بتزيد في الدائن. لازم مجموع المدين يساوي مجموع الدائن.",
    ),
    (
        ("مدین", "کریڈٹ", "ڈیبٹ", "debit", "credit"),
        "Debit اور Credit اکاؤنٹنگ انٹری کے دو حصے ہیں۔ Assets اور Expenses عموماً Debit میں بڑھتے ہیں، جبکہ Liabilities, Equity اور Revenue عموماً Credit میں بڑھتے ہیں۔ ہر Journal Entry میں Debit کا کل Credit کے کل کے برابر ہونا چاہیے۔",
    ),
    (
        ("ডেবিট", "ক্রেডিট", "debit", "credit"),
        "ডেবিট ও ক্রেডিট হলো জার্নাল এন্ট্রির দুই দিক। সাধারণভাবে Assets ও Expenses ডেবিটে বাড়ে, আর Liabilities, Equity ও Revenue ক্রেডিটে বাড়ে। প্রতিটি এন্ট্রিতে মোট ডেবিট ও মোট ক্রেডিট সমান হতে হবে।",
    ),
    (
        ("مدين", "دائن", "المدين", "الدائن"),
        "المدين والدائن هما طرفا القيد المحاسبي. المدين هو الطرف الذي تزيد فيه الأصول والمصروفات أو تنقص فيه الالتزامات والإيرادات. الدائن هو الطرف الذي تزيد فيه الالتزامات والإيرادات وحقوق الملكية أو تنقص فيه الأصول. القاعدة المهمة: مجموع المدين يجب أن يساوي مجموع الدائن في كل قيد.",
    ),
    (
        ("الأصول", "اصل", "أصل", "asset"),
        "الأصول هي موارد تملكها المنشأة أو تسيطر عليها ويتوقع أن تحقق منها منفعة مستقبلية، مثل النقدية، البنك، العملاء، المخزون، المعدات، وسلف الموظفين. غالبا تزيد الأصول في الجانب المدين وتنقص في الجانب الدائن.",
    ),
    (
        ("الخصوم", "الالتزامات", "liability"),
        "الخصوم أو الالتزامات هي مبالغ مستحقة على المنشأة للغير، مثل الموردين، القروض، ضريبة القيمة المضافة المستحقة، والرواتب المستحقة. غالبا تزيد الخصوم في الجانب الدائن وتنقص في الجانب المدين.",
    ),
    (
        ("حقوق الملكية", "رأس المال", "راس المال", "equity"),
        "حقوق الملكية تمثل صافي حق المالك في المنشأة بعد طرح الالتزامات من الأصول. تشمل رأس المال والأرباح المحتجزة والمسحوبات. تزيد غالبا في الجانب الدائن وتنقص في الجانب المدين.",
    ),
    (
        ("الإيرادات", "الايرادات", "إيراد", "مبيعات"),
        "الإيرادات هي ما تحققه المنشأة من بيع السلع أو تقديم الخدمات. في قيد البيع غالبا تكون الإيرادات دائنة، ويقابلها مدين في الصندوق أو البنك أو العملاء حسب طريقة الدفع.",
    ),
    (
        ("المصروفات", "مصروف", "expense"),
        "المصروفات هي تكاليف تتحملها المنشأة لتشغيل النشاط أو تحقيق الإيراد، مثل الرواتب والإيجار والمصاريف الإدارية. غالبا تزيد المصروفات في الجانب المدين وتؤثر بتخفيض الربح.",
    ),
    (
        ("القيد المزدوج", "القيد المزدوج", "double entry"),
        "القيد المزدوج يعني أن كل عملية مالية تسجل بطرفين على الأقل: مدين ودائن. لا يكون القيد صحيحا إلا إذا تساوى مجموع المدين مع مجموع الدائن.",
    ),
    (
        ("ميزان المراجعة", "trial balance"),
        "ميزان المراجعة تقرير يجمع أرصدة الحسابات المدينة والدائنة للتأكد من توازن التسجيل المحاسبي. توازنه لا يعني عدم وجود أخطاء، لكنه يكشف أخطاء عدم التوازن.",
    ),
    (
        ("قائمة الدخل", "الدخل", "الربح والخسارة"),
        "قائمة الدخل تعرض الإيرادات والمصروفات خلال فترة معينة للوصول إلى صافي الربح أو الخسارة. صافي الربح يساوي الإيرادات ناقص المصروفات.",
    ),
    (
        ("الميزانية", "المركز المالي", "balance sheet"),
        "قائمة المركز المالي تعرض الأصول والخصوم وحقوق الملكية في تاريخ معين. معادلتها الأساسية: الأصول = الخصوم + حقوق الملكية.",
    ),
    (
        ("التدفق النقدي", "السيولة", "cash flow"),
        "التدفق النقدي يوضح حركة دخول وخروج النقد. قد تحقق المنشأة ربحا محاسبيا ومع ذلك تعاني من نقص السيولة إذا تأخر تحصيل العملاء أو زاد المخزون أو المصروفات النقدية.",
    ),
    (
        ("ضريبة القيمة المضافة", "القيمة المضافة", "vat"),
        "ضريبة القيمة المضافة تظهر في المبيعات كضريبة مخرجات وفي المشتريات كضريبة مدخلات. صافي الضريبة المستحقة غالبا يساوي ضريبة المخرجات ناقص ضريبة المدخلات.",
    ),
    (
        ("تكلفة البضاعة", "تكلفة المبيعات", "cogs"),
        "تكلفة البضاعة المباعة هي تكلفة الأصناف التي تم بيعها. عند البيع يثبت النظام الإيراد، ويثبت أيضا تكلفة البضاعة المباعة مقابل تخفيض المخزون.",
    ),
    (
        ("الذمم المدينة", "العملاء", "receivable"),
        "الذمم المدينة هي مبالغ مستحقة للمنشأة على العملاء نتيجة البيع الآجل. تزيد عند البيع الآجل وتنخفض عند التحصيل.",
    ),
    (
        ("الذمم الدائنة", "الموردين", "payable"),
        "الذمم الدائنة هي مبالغ مستحقة على المنشأة للموردين. تزيد عند الشراء الآجل وتنخفض عند السداد.",
    ),
]


def _answer_greeting(text: str) -> str | None:
    normalized = _extract_user_question(text).strip().lower()
    if not normalized:
        return None
    for words, answer in GENERAL_CHAT_PATTERNS:
        if any(word in normalized for word in words):
            return answer
    if any(word in normalized for word in ("السلام عليكم", "سلام عليكم", "مرحبا", "أهلا", "اهلا", "هلا", "صباح الخير", "مساء الخير")):
        if any(word in normalized for word in ("كيفك", "وش", "ابشر", "الله يعطيك")):
            return "وعليكم السلام ورحمة الله وبركاته، حيّاك الله. أبشر، أنا معك كمساعد محاسبي ودود داخل النظام. أقدر أساعدك في الفواتير، القيود، الرواتب، السلف، التقارير، وشرح المفاهيم المحاسبية بطريقة بسيطة ومفيدة."
        return (
            "وعليكم السلام ورحمة الله وبركاته، أهلا وسهلا بك. نورت النظام. "
            "أنا مساعدك المحاسبي داخل النظام. أستطيع مساعدتك في استخدام النظام، شرح المفاهيم المحاسبية، "
            "تحليل المبيعات والمشتريات والمخزون، ومساعدتك في الفواتير والرواتب والسلف والقيود."
        )
    if any(word in normalized for word in ("يا زول", "كيفنك", "عامل شنو", "السلام عليكن", "مرحبتين")):
        return "وعليكم السلام، مرحبتين بيك يا زول. أنا مساعدك المحاسبي في النظام، بقدر أساعدك في الفواتير والقيود والرواتب والسلف والتقارير وشرح المحاسبة بطريقة واضحة."
    if any(word in normalized for word in ("السلام علیکم", "السلام عليكم", "آداب", "خوش آمدید", "ہیلو", "ہیلو")):
        return "وعلیکم السلام، خوش آمدید۔ میں آپ کا اکاؤنٹنگ اسسٹنٹ ہوں۔ میں سسٹم کے استعمال، انوائسز، جرنل انٹریز، تنخواہوں، ایڈوانسز، رپورٹس اور اکاؤنٹنگ تصورات میں مدد کر سکتا ہوں۔"
    if any(word in normalized for word in ("আসসালামু", "সালাম", "নমস্কার", "হ্যালো", "স্বাগতম")):
        return "ওয়ালাইকুম আসসালাম, স্বাগতম। আমি আপনার হিসাবরক্ষণ সহকারী। আমি সিস্টেম ব্যবহার, ইনভয়েস, জার্নাল এন্ট্রি, বেতন, অগ্রিম, রিপোর্ট এবং হিসাববিজ্ঞানের ধারণা বুঝতে সাহায্য করতে পারি।"
    if any(greeting in normalized for greeting in GREETING_PATTERNS):
        return (
            "وعليكم السلام ورحمة الله وبركاته، أهلا وسهلا بك. "
            "أنا مساعدك المحاسبي داخل النظام. أستطيع مساعدتك في استخدام النظام، شرح المفاهيم المحاسبية، "
            "تحليل المبيعات والمشتريات والمخزون، ومساعدتك في الفواتير والرواتب والسلف والقيود."
        )
    return None


SYSTEM_USAGE_PATTERNS = [
    (
        ("كيف اضيف فاتورة", "كيف أضيف فاتورة", "ابغى اضيف فاتورة", "ابي اضيف فاتورة", "وين اضيف فاتورة"),
        "لإضافة فاتورة: إذا كانت بيع افتح فواتير البيع ثم إضافة فاتورة بيع. وإذا كانت شراء افتح فواتير الشراء ثم إضافة فاتورة شراء. اختر العميل أو المورد، أضف الأصناف والكميات والأسعار، ثم احفظ وراجع القيد عند الترحيل.",
    ),
    (
        ("عايز اضيف فاتورة", "داير اضيف فاتورة", "اضيف فاتورة كيف", "كيف اضيف فاتورة يا زول"),
        "عشان تضيف فاتورة: لو فاتورة بيع افتح فواتير البيع ثم إضافة فاتورة بيع. ولو فاتورة شراء افتح فواتير الشراء ثم إضافة فاتورة شراء. اختار العميل أو المورد، أدخل الأصناف والكميات والأسعار، وبعدها احفظ.",
    ),
    (
        ("انوائس کیسے", "انوائس بنانا", "invoice kaise", "بل کیسے", "رسید کیسے"),
        "Invoice بنانے کے لیے: Sales Invoice کے لیے فواتير البيع ثم إضافة فاتورة بيع کھولیں، Purchase Invoice کے لیے فواتير الشراء ثم إضافة فاتورة شراء کھولیں۔ Customer یا Supplier منتخب کریں، items, quantities اور prices شامل کریں، پھر save کریں۔",
    ),
    (
        ("ইনভয়েস", "চালান", "invoice kivabe", "invoice কিভাবে", "বিল কিভাবে"),
        "ইনভয়েস যোগ করতে: Sales invoice হলে فواتير البيع ثم إضافة فاتورة بيع খুলুন, Purchase invoice হলে فواتير الشراء ثم إضافة فاتورة شراء খুলুন। Customer বা Supplier নির্বাচন করুন, items, quantities এবং prices লিখে save করুন।",
    ),
    (
        ("كيف أبدأ", "ابدأ استخدام", "استخدام النظام", "أستخدم النظام", "تشغيل النظام"),
        "لبداية استخدام النظام: سجل الدخول، ثم اختر الشركة والفرع من صفحة اختيار الشركة والفرع. بعد ذلك أدخل العملاء والموردين والأصناف، ثم ابدأ بإضافة فواتير البيع والشراء. راقب النتائج من لوحة التحكم ومركز التقارير.",
    ),
    (
        ("اختيار الشركة", "اختار الشركة", "اختيار الفرع", "اختر الفرع", "الشركة والفرع"),
        "لاختيار الشركة والفرع: افتح صفحة اختيار الشركة والفرع من القائمة الجانبية، اختر الشركة ثم الفرع، ثم احفظ. إذا لم تختر فرعا فقد لا تظهر بيانات الفواتير والمخزون والتقارير.",
    ),
    (
        ("فاتورة بيع", "إضافة بيع", "اضافة بيع", "أضيف فاتورة بيع", "انشاء فاتورة بيع"),
        "لإضافة فاتورة بيع: افتح فواتير البيع ثم إضافة فاتورة بيع. اختر العميل وطريقة الدفع والتاريخ، أضف الأصناف والكميات والأسعار، ثم احفظ. بعد ذلك يمكنك ترحيل الفاتورة محاسبيا وعرض القيد المرتبط.",
    ),
    (
        ("فاتورة شراء", "إضافة شراء", "اضافة شراء", "أضيف فاتورة شراء", "انشاء فاتورة شراء"),
        "لإضافة فاتورة شراء: افتح فواتير الشراء ثم إضافة فاتورة شراء. اختر المورد والتاريخ، أضف الأصناف والكميات والأسعار، ثم احفظ. النظام يزيد المخزون ويربط الفاتورة بالقيد عند الترحيل.",
    ),
    (
        ("فاتورة مصورة", "صورة فاتورة", "قراءة فاتورة", "ocr", "رفع فاتورة"),
        "لاستخدام الفاتورة المصورة: افتح إضافة فاتورة بالنموذج الخاص، ارفع صورة واضحة أو PDF نصي، ثم راجع البيانات المستخرجة قبل الحفظ. إذا كانت الصورة غير واضحة لا تعتمدها قبل التصحيح.",
    ),
    (
        ("أضيف صنف", "اضافة صنف", "إضافة صنف", "المخزون", "الأصناف"),
        "لإضافة صنف: افتح المخزون ثم إضافة صنف. أدخل اسم الصنف والتكلفة وسعر البيع والكمية وحد التنبيه، ثم احفظه ليظهر في فواتير البيع والشراء.",
    ),
    (
        ("أضيف عميل", "اضافة عميل", "إضافة عميل", "العملاء"),
        "لإضافة عميل: افتح العملاء ثم إضافة عميل. أدخل الاسم وبيانات التواصل والرقم الضريبي إن وجد، ثم احفظه لاستخدامه في فواتير البيع.",
    ),
    (
        ("أضيف مورد", "اضافة مورد", "إضافة مورد", "الموردين"),
        "لإضافة مورد: افتح الموردين ثم إضافة مورد. أدخل اسم المورد وبياناته الأساسية، ثم استخدمه عند تسجيل فواتير الشراء.",
    ),
    (
        ("قيد يومية", "إضافة قيد", "اضافة قيد", "القيود اليومية"),
        "لإضافة قيد يومية: افتح القيود اليومية ثم إضافة قيد. أدخل التاريخ والوصف، ثم أضف سطور المدين والدائن وتأكد أن مجموع المدين يساوي مجموع الدائن قبل الحفظ.",
    ),
    (
        ("اعتماد راتب", "دفع راتب", "رواتب الموظفين", "مسير الرواتب"),
        "لاستخدام الرواتب: افتح رواتب الموظفين. أنشئ الراتب ثم اضغط اعتماد لإنشاء قيد الاستحقاق. بعد الاعتماد اضغط دفع لإنشاء قيد الصرف. لا تعتمد أو تدفع راتبا داخل شهر مقفل.",
    ),
    (
        ("سلفة موظف", "سلف الموظفين", "إضافة سلفة", "اضافة سلفة"),
        "لإضافة سلفة موظف: افتح سلف الموظفين ثم إضافة سلفة. اختر الموظف والمبلغ والتاريخ وطريقة الصرف. عند خصم السلفة من الراتب يحدث النظام الرصيد وحالة السلفة.",
    ),
    (
        ("القفل الشهري", "قفل شهر", "شهر مقفل", "إعادة فتح شهر"),
        "لاستخدام القفل الشهري: افتح القفل الشهري ثم إضافة قفل، واختر الشركة والسنة والشهر. بعد القفل يمنع النظام الترحيل أو الاعتماد أو الدفع داخل الشهر حتى يتم إعادة فتحه.",
    ),
    (
        ("العمليات غير المرحلة", "غير مرحلة", "لم ترحل", "عرض القيد"),
        "لمراجعة العمليات غير المرحلة: افتح مركز التقارير ثم تقرير العمليات غير المرحلة. أي فاتورة أو راتب أو سلفة لا تملك قيدا ستظهر هناك. من الصفحات المرتبطة يمكنك استخدام عرض القيد عند توفره.",
    ),
    (
        ("المساعد الصوتي", "الدردشة الصوتية", "تحدث", "أوامر صوتية"),
        "لاستخدام المساعد الصوتي: افتح المساعد المالي، اضغط تحدث، قل طلبك مثل افتح كشف الرواتب أو حلل المبيعات. سيحول النظام الصوت إلى نص ثم يعرض الإجابة أو زر الانتقال للصفحة المناسبة.",
    ),
    (
        ("الصلاحيات", "لا تظهر", "لا أرى", "غير مسموح"),
        "إذا لم تظهر صفحة أو زر، فتأكد أولا من اختيار الشركة والفرع، ثم راجع صلاحيات دور المستخدم. بعض الصفحات تحتاج صلاحية عرض أو إضافة أو تعديل.",
    ),
]


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _extract_user_question(text: str) -> str:
    markers = (
        "سؤال المستخدم:",
        "سؤال:",
        "User question:",
        "question:",
        "ط³ط¤ط§ظ„ ط§ظ„ظ…ط³طھط®ط¯ظ…:",
        "ط³ط¤ط§ظ„:",
    )
    for marker in markers:
        if marker in text:
            return text.rsplit(marker, 1)[-1].strip()
    return text.strip()


def _remember_user_information(question: str) -> str | None:
    normalized = normalize_user_question_text(_extract_user_question(question))
    lowered = normalized.lower()
    memory_markers = ("تذكر", "احفظ", "خزن", "خزّن", "معلومة عني", "معلومة مهمة")
    if not any(marker in lowered for marker in memory_markers):
        return None
    cleaned = normalized
    for marker in memory_markers:
        cleaned = re.sub(rf"(?<!\w){re.escape(marker)}(?!\w)", "", cleaned, flags=re.IGNORECASE).strip(" :،-")
    if not cleaned:
        return "اكتب المعلومة التي تريد حفظها بعد كلمة: تذكر."
    if cleaned not in USER_MEMORY:
        USER_MEMORY.append(cleaned[:500])
        del USER_MEMORY[:-30]
    return f"تم حفظ المعلومة للاستفادة منها داخل جلسة خدمة الذكاء الحالية: {cleaned}"


def _answer_from_user_memory(question: str) -> str | None:
    if not USER_MEMORY:
        return None
    normalized = normalize_user_question_text(_extract_user_question(question)).lower()
    if not any(term in normalized for term in ("ماذا تذكر", "وش تذكر", "معلوماتي", "الذي حفظته", "ما الذي تعرفه عني")):
        return None
    return "المعلومات المحفوظة في جلسة الذكاء الحالية:\n" + "\n".join(f"- {item}" for item in USER_MEMORY[-10:])


def _open_web_search_answer(question: str) -> str | None:
    if LOCAL_ANALYSIS_ONLY or not ENABLE_OPEN_WEB_SEARCH:
        return None
    analysis = _analyze_question(question)
    if not analysis.get("asks_web"):
        return None

    query = analysis["normalized_text"]
    query = re.sub(r"\b(ابحث|بحث|في النت|على النت|في الانترنت|في الإنترنت|روابط|مصادر)\b", "", query, flags=re.IGNORECASE).strip()
    if not query:
        return "اكتب موضوع البحث بوضوح، وسأحاول جلب ملخص من مصادر مفتوحة."

    sources: list[tuple[str, str, str]] = []
    headers = {"User-Agent": "AccountingAIService/1.1 (+open web research)"}

    try:
        response = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers=headers,
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
        abstract = (data.get("AbstractText") or "").strip()
        url = (data.get("AbstractURL") or "").strip()
        title = (data.get("Heading") or "DuckDuckGo").strip()
        if abstract and url:
            sources.append((title, abstract, url))
    except Exception:
        pass

    try:
        response = requests.get(
            "https://ar.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(query),
            headers=headers,
            timeout=12,
        )
        if response.status_code == 404:
            response = requests.get(
                "https://en.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(query),
                headers=headers,
                timeout=12,
            )
        response.raise_for_status()
        data = response.json()
        extract = (data.get("extract") or "").strip()
        url = ((data.get("content_urls") or {}).get("desktop") or {}).get("page", "")
        title = (data.get("title") or "Wikipedia").strip()
        if extract and url:
            sources.append((title, extract, url))
    except Exception:
        pass

    try:
        response = requests.get(
            "https://api.openalex.org/works",
            params={"search": query, "per-page": 2},
            headers=headers,
            timeout=12,
        )
        response.raise_for_status()
        for item in (response.json().get("results") or [])[:2]:
            title = (item.get("title") or "OpenAlex research").strip()
            abstract = (item.get("abstract_inverted_index") and "بحث أكاديمي مفهرس عن الموضوع.") or ""
            url = (item.get("doi") or item.get("id") or "").strip()
            if title and url:
                sources.append((title, abstract, url))
    except Exception:
        pass

    if not sources:
        return "حاولت البحث في مصادر مفتوحة، لكن لم أجد نتيجة موثوقة كافية الآن. جرّب صياغة أدق أو اسأل عن مصدر محدد."

    unique_sources = []
    seen = set()
    for title, summary, url in sources:
        if url in seen:
            continue
        seen.add(url)
        unique_sources.append((title, summary, url))

    lines = [f"نتيجة بحث مفتوح عن: {query}", "", "الخلاصة:"]
    for index, (title, summary, url) in enumerate(unique_sources[:4], start=1):
        concise = re.sub(r"\s+", " ", summary).strip()
        if len(concise) > 420:
            concise = concise[:417].rstrip() + "..."
        lines.append(f"{index}. {title}: {concise or 'مصدر مفيد للمراجعة.'}")
    lines.append("")
    lines.append("روابط التحقق:")
    for title, _summary, url in unique_sources[:4]:
        lines.append(f"- {title}: {url}")
    return "\n".join(lines)


def _wants_financial_context_answer(text: str) -> bool:
    user_question = _extract_user_question(text).lower()
    keywords = (
        "حلل",
        "تحليل",
        "مؤشرات",
        "توصيات",
        "الأداء",
        "اداء",
        "المبيعات",
        "المشتريات",
        "المخزون",
        "التدفق",
        "الربح",
        "الخسارة",
        "بيانات الفرع",
        "financial",
        "analysis",
        "ط­ظ„ظ„",
        "طھط­ظ„ظٹظ„",
        "ظ…ط¤ط´ط±ط§طھ",
    )
    return any(keyword in user_question for keyword in keywords)


def _answer_from_financial_context(question: str) -> str | None:
    if not _wants_financial_context_answer(question):
        return None

    context = _extract_json_object(question)
    if not context:
        return None

    sales = _money(context.get("sales_total"))
    purchases = _money(context.get("purchases_total"))
    inventory = _money(context.get("inventory_value"))
    low_stock = int(_money(context.get("low_stock_count")))
    invoice_count = int(_money(context.get("invoice_count")))
    purchase_count = int(_money(context.get("purchase_count")))

    lines = [
        "قراءة النموذج للبيانات الحالية:",
        f"- المبيعات: {sales:.2f}",
        f"- المشتريات: {purchases:.2f}",
        f"- قيمة المخزون: {inventory:.2f}",
        f"- عدد فواتير البيع: {invoice_count}",
        f"- عدد فواتير الشراء: {purchase_count}",
    ]

    if sales <= 0 and purchases <= 0:
        lines.append("- لا توجد حركة كافية للحكم على الأداء؛ ابدأ بإدخال الفواتير وترحيلها محاسبيا.")
    elif purchases > sales:
        lines.append("- المشتريات أعلى من المبيعات؛ راجع المخزون البطيء وخطة الشراء.")
    else:
        lines.append("- المبيعات تغطي المشتريات في الفترة الحالية، ويفضل متابعة هامش الربح والتحصيل.")

    if low_stock:
        lines.append(f"- يوجد {low_stock} صنف عند حد التنبيه أو أقل؛ راجع إعادة الطلب.")
    if inventory <= 0:
        lines.append("- قيمة المخزون صفر أو غير مسجلة؛ تأكد من إدخال تكاليف الأصناف وفواتير الشراء.")

    lines.append("- الأولوية: راجع العمليات غير المرحلة، ثم المخزون، ثم التحصيل والسلف والرواتب.")
    return "\n".join(lines)


def _decode_payload_text(image_base64: str) -> str:
    try:
        raw = base64.b64decode(image_base64, validate=False)
    except (ValueError, TypeError):
        return ""

    snippets: list[str] = []
    for encoding in ("utf-8", "utf-16", "windows-1256", "cp1252", "latin-1"):
        try:
            decoded = raw.decode(encoding, errors="ignore")
        except LookupError:
            continue
        decoded = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", decoded)
        if len(decoded.strip()) >= 20:
            snippets.append(decoded)

    merged = "\n".join(snippets)
    return re.sub(r"\s+", " ", merged).strip()[:12000]


def _preprocess_invoice_image(raw: bytes):
    if Image is None:
        return None
    try:
        image = Image.open(io.BytesIO(raw))
    except Exception:
        return None

    image = ImageOps.exif_transpose(image)
    image = image.convert("L")
    max_side = max(image.size)
    if max_side and max_side < 1800:
        scale = 1800 / max_side
        image = image.resize((int(image.width * scale), int(image.height * scale)))
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image).enhance(1.8)
    image = ImageEnhance.Sharpness(image).enhance(1.6)
    image = image.filter(ImageFilter.MedianFilter(size=3))
    return image


def _ocr_invoice_image(image_base64: str, media_type: str | None = None) -> tuple[str, str]:
    if not image_base64 or not (media_type or "").lower().startswith("image/"):
        return "", ""
    if Image is None:
        return "", "مكتبة Pillow غير مثبتة، لذلك لم يتم تحسين الصورة قبل القراءة."
    if pytesseract is None:
        return "", "مكتبة pytesseract غير مثبتة، لذلك لم يتم تشغيل قراءة OCR للصورة."

    try:
        raw = base64.b64decode(image_base64, validate=False)
    except (ValueError, TypeError):
        return "", "تعذر فك ترميز الصورة المرفقة."

    image = _preprocess_invoice_image(raw)
    if image is None:
        return "", "تعذر فتح الصورة المرفقة لمعالجتها."

    configs = [
        ("ara+eng", "--psm 6"),
        ("eng", "--psm 6"),
        ("ara+eng", "--psm 11"),
    ]
    texts: list[str] = []
    warnings: list[str] = []
    for lang, config in configs:
        try:
            text = pytesseract.image_to_string(image, lang=lang, config=config)
        except Exception as exc:
            warnings.append(str(exc)[:180])
            continue
        text = re.sub(r"\s+", " ", text or "").strip()
        if len(text) >= 10:
            texts.append(text)

    if texts:
        return "\n".join(dict.fromkeys(texts))[:12000], ""
    if warnings:
        return "", "لم يستطع OCR قراءة النص من الصورة. تأكد من تثبيت Tesseract مع اللغتين العربية والإنجليزية على الخادم."
    return "", "لم يستخرج OCR نصا واضحا من الصورة."


def _parse_amount(text: str, labels: tuple[str, ...]) -> float:
    for label in labels:
        if label == "total":
            label_pattern = r"(?<!sub\s)(?<!grand\s)(?<![a-zA-Z])total(?![a-zA-Z])"
        else:
            label_pattern = rf"(?<![a-zA-Z]){label}(?![a-zA-Z])"
        pattern = rf"{label_pattern}\s*[:\-]?\s*(?:SAR|ر\.س|ريال)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _money(match.group(1).replace(",", ""))
    return 0.0


def _parse_field(text: str, labels: tuple[str, ...]) -> str:
    stop_words = (
        "invoice_number|invoice no|invoice number|date|subtotal|sub total|total|vat|tax|"
        "supplier_name|supplier|vendor|رقم الفاتورة|التاريخ|قبل الضريبة|الإجمالي|المجموع|ضريبة|المورد|البائع"
    )
    for label in labels:
        pattern = rf"(?<![a-zA-Z]){label}(?![a-zA-Z])\s*[:\-]?\s*(.+?)(?=\s+(?:{stop_words})\s*[:\-]?|[\n\r|,؛]|$)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _parse_date(text: str) -> str:
    patterns = [
        r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})",
        r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        parts = [int(x) for x in match.groups()]
        if parts[0] > 1900:
            year, month, day = parts
        else:
            day, month, year = parts
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return date.today().isoformat()


def _parse_invoice_items(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    line_pattern = re.compile(
        r"(?P<name>[\u0600-\u06ffa-zA-Z][\u0600-\u06ffa-zA-Z0-9 ._\-]{2,60})\s+"
        r"(?P<qty>\d+(?:\.\d+)?)\s+"
        r"(?P<price>\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    for match in line_pattern.finditer(text):
        name = match.group("name").strip()
        if any(word in name.lower() for word in ("total", "subtotal", "vat", "invoice", "الاجمالي", "الضريبة")):
            continue
        items.append({
            "name": name,
            "quantity": _money(match.group("qty")),
            "unit_price": _money(match.group("price")),
        })
        if len(items) >= 25:
            break
    return items


def extract_invoice_data(question: str, image_base64: str | None = None, media_type: str | None = None) -> dict[str, Any]:
    text = question or ""
    is_image = (media_type or "").lower().startswith("image/")
    decoded = "" if is_image else _decode_payload_text(image_base64 or "")
    ocr_text, ocr_warning = _ocr_invoice_image(image_base64 or "", media_type)
    searchable = f"{text}\n{decoded}\n{ocr_text}".strip()

    supplier_name = _parse_field(searchable, ("supplier_name", "supplier", "vendor", "اسم المورد", "المورد", "البائع"))
    invoice_number = _parse_field(searchable, ("invoice_number", "invoice no", "invoice number", "رقم الفاتورة", "فاتورة رقم"))
    subtotal = _parse_amount(searchable, ("subtotal", "sub total", "قبل الضريبة", "الإجمالي قبل الضريبة", "المجموع قبل الضريبة"))
    vat = _parse_amount(searchable, ("vat", "tax", "ضريبة", "ضريبة القيمة المضافة"))
    total = _parse_amount(searchable, ("total", "grand total", "amount due", "الإجمالي", "المجموع", "الصافي"))
    items = _parse_invoice_items(searchable)

    if not any((supplier_name, invoice_number, subtotal, vat, total, items)):
        return {
            "error": ocr_warning or "لم أتمكن من قراءة بيانات الفاتورة من الصورة. ارفع صورة أوضح، أو PDF نصي، أو أدخل البيانات يدويا ثم أعد المحاولة.",
            "media_type": media_type or "",
            "supplier_name": "",
            "invoice_number": "",
            "issue_date": date.today().isoformat(),
            "subtotal": 0,
            "vat": 0,
            "total": 0,
            "items": [],
        }

    if total and not subtotal and vat:
        subtotal = max(total - vat, 0)
    if subtotal and not total:
        total = subtotal + vat

    return {
        "supplier_name": supplier_name or "مورد من الفاتورة",
        "invoice_number": invoice_number or f"AI-{date.today().strftime('%Y%m%d')}",
        "issue_date": _parse_date(searchable),
        "subtotal": round(subtotal, 2),
        "vat": round(vat, 2),
        "total": round(total, 2),
        "items": items,
        "media_type": media_type or "",
        "ocr_warning": ocr_warning,
    }


class PrivateAccountingModel:
    def __init__(self, model_path: Path = MODEL_PATH):
        self.model_path = Path(model_path)
        self.tokenizer = None
        self.model = None
        if not self.model_path.exists():
            return

        torch_runtime, model_cls, tokenizer_cls = _load_transformers_runtime()
        if torch_runtime is None or model_cls is None or tokenizer_cls is None:
            return

        self.torch = torch_runtime

        self.tokenizer = tokenizer_cls.from_pretrained(self.model_path)
        self.model = model_cls.from_pretrained(self.model_path)

        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        self.model.config.pad_token_id = self.tokenizer.pad_token_id
        self.model.eval()

    def build_prompt(self, question: str) -> str:
        question = normalize_user_question_text(question)
        return f"{SYSTEM_PROMPT}\n\nسؤال: {question}\nالإجابة:"

    def build_chat_prompt(self, question: str) -> str:
        question = normalize_user_question_text(question)
        analysis = _analyze_question(question)
        memory_context = "\n".join(f"- {item}" for item in USER_MEMORY[-10:]) if USER_MEMORY else "لا توجد معلومات محفوظة بعد."
        return (
            f"{SYSTEM_PROMPT}\n\n"
            f"تحليل السؤال قبل الإجابة:\n{json.dumps(analysis, ensure_ascii=False)}\n\n"
            f"معلومات محفوظة من المستخدم:\n{memory_context}\n\n"
            "تعليمات الجودة:\n"
            "- أجب كخبير مالي ومحاسبي عملي، لا كروبوت عام.\n"
            "- حلل نية المستخدم أولا: هل يريد شرحا، تنفيذا، بحثا في النت، أم تحليلا من بيانات النظام.\n"
            "- إذا كان السؤال يطلب بحثا حديثا أو روابط تحقق فاعتمد على نتائج البحث المفتوح المرسلة لك ولا تخترع مصادر.\n"
            "- اربط الإجابة بالأرقام والسياق الموجود في السؤال عندما تتوفر.\n"
            "- إذا كان السؤال عن النظام أو الشركة فاعتمد على البيانات المرسلة من Django ولا تخترع أرقاما.\n"
            "- اجعل الرد منظما: خلاصة، تحليل، توصية عملية، وما يحتاجه المستخدم للخطوة التالية.\n"
            "- في الصوت العربي استخدم جملا قصيرة وواضحة وسهلة النطق.\n"
            "- لا تقدم فتوى أو حكم شرعي؛ وجّه المستخدم لأهل العلم عند السؤال الشرعي.\n\n"
            f"سؤال المستخدم والسياق:\n{question}\n\nالإجابة الاحترافية:"
        )

    def answer(self, question: str, max_new_tokens: int = 240) -> str:
        if not question or not question.strip():
            raise ValueError("السؤال لا يمكن أن يكون فارغا.")

        question = normalize_user_question_text(question)

        memory_answer = _remember_user_information(question)
        if memory_answer:
            return memory_answer

        recalled_memory = _answer_from_user_memory(question)
        if recalled_memory:
            return recalled_memory

        if not LOCAL_ANALYSIS_ONLY:
            web_answer = _open_web_search_answer(question)
            if web_answer:
                return web_answer

        if AI_BACKEND in {"local_model", "transformers"} or REQUIRE_LOCAL_MODEL:
            if self.model is None or self.tokenizer is None:
                raise ValueError(
                    "تم ضبط الخدمة على استخدام موديلك المحلي فقط، لكن أوزان الموديل غير موجودة أو لم يتم تحميلها. "
                    "ارفع الموديل إلى accounting_ai_service/models/my_model أو اضبط ACCOUNTING_AI_MODEL_PATH."
                )
            return self._answer_from_transformers(question, max_new_tokens=max_new_tokens)

        if AI_BACKEND in {"openai", "openai_compatible", "hosted"} and not OPENAI_COMPATIBLE_API_KEY:
            raise ValueError("خدمة الذكاء الاصطناعي مضبوطة على hosted/openai_compatible لكن OPENAI_COMPATIBLE_API_KEY غير موجود في Render.")

        if not LOCAL_ANALYSIS_ONLY:
            hosted_answer = self._answer_from_openai_compatible(question, max_new_tokens=max_new_tokens)
            if hosted_answer:
                return hosted_answer

        if REQUIRE_HOSTED_AI:
            raise ValueError("تم تفعيل REQUIRE_HOSTED_AI لكن المزود الخارجي لم يرجع إجابة. راجع OPENAI_COMPATIBLE_API_KEY و OPENAI_COMPATIBLE_MODEL و OPENAI_COMPATIBLE_BASE_URL.")

        greeting_answer = _answer_greeting(question)
        if greeting_answer:
            return greeting_answer

        private_answer = self._answer_from_private_knowledge(question)
        if private_answer:
            return private_answer

        if not LOCAL_ANALYSIS_ONLY:
            ollama_answer = self._answer_from_ollama(question, max_new_tokens=max_new_tokens)
            if ollama_answer:
                return ollama_answer

        if self.model is None or self.tokenizer is None:
            return (
                "لم يتم تحميل أوزان النموذج على الخادم، لذلك أعمل حاليا بطبقة المعرفة المحاسبية المدمجة.\n"
                "- أستطيع الإجابة عن الرواتب والسلف وفواتير البيع والشراء.\n"
                "- أستطيع شرح القيود والضريبة والمخزون والتقارير.\n"
                "- إذا سألت عن أكثر من موضوع سأجمع لك الإجابة في نقاط متعددة."
            )

        return self._answer_from_transformers(question, max_new_tokens=max_new_tokens)

    def _answer_from_transformers(self, question: str, max_new_tokens: int = 240) -> str:
        with self.torch.inference_mode():
            prompt = self.build_prompt(question)
            inputs = self.tokenizer(prompt, return_tensors="pt")

            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                no_repeat_ngram_size=3,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

            decoded = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        answer = self._clean_answer(decoded, prompt)
        if not self._is_usable_arabic_answer(answer):
            return "هذا السؤال يحتاج تدريبا إضافيا داخل النموذج الخاص. أضف مثالا مشابها في بيانات التدريب ثم شغل train.py لتحسين الإجابة."
        return answer

    def _answer_from_ollama(self, question: str, max_new_tokens: int = 420) -> str | None:
        if AI_BACKEND not in {"auto", "ollama"} or not OLLAMA_MODEL:
            return None
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": self.build_chat_prompt(question),
            "stream": False,
            "options": {
                "num_predict": min(int(max_new_tokens or 420), 1800),
                "temperature": 0.2,
                "top_p": 0.9,
                "repeat_penalty": 1.08,
            },
        }
        try:
            response = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None
        answer = (data.get("response") or "").strip()
        if not answer or not self._is_usable_arabic_answer(answer):
            return None
        return self._clean_answer(answer, "")

    def _answer_from_openai_compatible(self, question: str, max_new_tokens: int = 420) -> str | None:
        if AI_BACKEND not in {"auto", "openai", "openai_compatible", "hosted"}:
            return None
        if not OPENAI_COMPATIBLE_API_KEY or not OPENAI_COMPATIBLE_MODEL:
            return None
        payload = {
            "model": OPENAI_COMPATIBLE_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self.build_chat_prompt(question)},
            ],
            "temperature": 0.2,
            "top_p": 0.9,
            "max_tokens": min(int(max_new_tokens or 420), 1800),
        }
        headers = {
            "Authorization": f"Bearer {OPENAI_COMPATIBLE_API_KEY}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                f"{OPENAI_COMPATIBLE_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None
        choices = data.get("choices") or []
        if not choices:
            return None
        answer = ((choices[0].get("message") or {}).get("content") or "").strip()
        if not answer or not self._is_usable_arabic_answer(answer):
            return None
        return self._clean_answer(answer, "")

    @staticmethod
    def _answer_from_private_knowledge(question: str) -> str | None:
        user_question = _extract_user_question(question)
        normalized_question = user_question.strip().lower()

        matched_sections: list[str] = []
        for words, answer in ACCOUNTING_CONCEPT_PATTERNS:
            if _contains_any(normalized_question, words):
                matched_sections.append(f"- مفهوم محاسبي: {answer}")

        for words, answer in SYSTEM_USAGE_PATTERNS:
            if _contains_any(normalized_question, words):
                matched_sections.append(f"- استخدام النظام: {answer}")

        for title, words, answer in ACCOUNTING_PATTERNS:
            if _contains_any(normalized_question, words):
                matched_sections.append(f"- {title}: {answer}")

        if matched_sections:
            if len(matched_sections) == 1:
                return matched_sections[0].removeprefix("- ").strip()
            return "إجابة مجمعة حسب المواضيع التي سألت عنها:\n" + "\n".join(matched_sections[:6])

        context_answer = _answer_from_financial_context(question)
        if context_answer:
            return context_answer

        exact_answers: list[str] = []
        best_key = None
        best_score = 0.0
        for key in PRIVATE_KNOWLEDGE:
            normalized_key = key.lower()
            if normalized_key in normalized_question:
                exact_answers.append(f"- {key}: {PRIVATE_KNOWLEDGE[key]}")
                continue

            score = SequenceMatcher(None, normalized_key, normalized_question).ratio()
            if score > best_score:
                best_key = key
                best_score = score

        if exact_answers:
            return "\n".join(exact_answers[:5])
        if best_key and best_score >= 0.45:
            return PRIVATE_KNOWLEDGE[best_key]
        return None

    @staticmethod
    def _clean_answer(decoded: str, prompt: str) -> str:
        answer = decoded.replace(prompt, "", 1).strip()
        answer = answer.replace("\ufffd", "").strip()
        if "سؤال:" in answer:
            answer = answer.split("سؤال:", 1)[0].strip()
        return answer or "لم أتمكن من تكوين إجابة واضحة. أعد صياغة السؤال من فضلك."

    @staticmethod
    def _is_usable_arabic_answer(answer: str) -> bool:
        arabic_chars = sum(1 for char in answer if "\u0600" <= char <= "\u06ff")
        latin_chars = sum(1 for char in answer if "a" <= char.lower() <= "z")
        return arabic_chars >= 10 and arabic_chars >= latin_chars


@lru_cache(maxsize=1)
def get_model() -> PrivateAccountingModel:
    return PrivateAccountingModel()


def ask(question: str, max_new_tokens: int = 240) -> str:
    return get_model().answer(question, max_new_tokens=max_new_tokens)


def runtime_status() -> dict[str, Any]:
    return {
        "model": MODEL_NAME,
        "backend": AI_BACKEND,
        "local_analysis_only": LOCAL_ANALYSIS_ONLY,
        "open_web_search_enabled": ENABLE_OPEN_WEB_SEARCH,
        "ollama_model": OLLAMA_MODEL,
        "ollama_url": OLLAMA_BASE_URL,
        "openai_compatible_model": OPENAI_COMPATIBLE_MODEL,
        "openai_compatible_base_url": OPENAI_COMPATIBLE_BASE_URL,
        "openai_compatible_configured": bool(OPENAI_COMPATIBLE_API_KEY),
        "require_hosted_ai": REQUIRE_HOSTED_AI,
        "require_local_model": REQUIRE_LOCAL_MODEL,
        "transformers_model_path": str(MODEL_PATH),
        "transformers_model_path_exists": MODEL_PATH.exists(),
        "transformers_loaded": bool(get_model.cache_info().currsize),
        "recommended_backend": "openai_compatible on Render, ollama on a server with RAM/GPU",
        "recommended_model": "OpenRouter/Groq/Together model via OpenAI-compatible API, or qwen2.5:7b-instruct with Ollama when RAM/GPU is enough",
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"{MODEL_NAME} جاهز.")
    print(ask("اشرح الرواتب والسلف والمبيعات والمشتريات"))
