import base64
import json
import re
import sys
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
except ImportError:
    torch = None
    AutoModelForCausalLM = None
    AutoTokenizer = None


MODEL_NAME = "نموذج عبدالرحمن المحاسبي"
MODEL_OWNER = "عبدالرحمن"
MODEL_PATH = Path(__file__).resolve().parent / "models" / "my_model"

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


def _answer_from_financial_context(question: str) -> str | None:
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
    decoded = _decode_payload_text(image_base64 or "")
    searchable = f"{text}\n{decoded}".strip()

    supplier_name = _parse_field(searchable, ("supplier_name", "supplier", "vendor", "اسم المورد", "المورد", "البائع"))
    invoice_number = _parse_field(searchable, ("invoice_number", "invoice no", "invoice number", "رقم الفاتورة", "فاتورة رقم"))
    subtotal = _parse_amount(searchable, ("subtotal", "sub total", "قبل الضريبة", "الإجمالي قبل الضريبة", "المجموع قبل الضريبة"))
    vat = _parse_amount(searchable, ("vat", "tax", "ضريبة", "ضريبة القيمة المضافة"))
    total = _parse_amount(searchable, ("total", "grand total", "amount due", "الإجمالي", "المجموع", "الصافي"))
    items = _parse_invoice_items(searchable)

    if not any((supplier_name, invoice_number, subtotal, vat, total, items)):
        return {
            "error": "لم أتمكن من قراءة بيانات الفاتورة من الصورة. ارفع صورة أوضح، أو PDF نصي، أو أدخل البيانات يدويا ثم أعد المحاولة.",
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
    }


class PrivateAccountingModel:
    def __init__(self, model_path: Path = MODEL_PATH):
        self.model_path = Path(model_path)
        self.tokenizer = None
        self.model = None
        if torch is None or AutoModelForCausalLM is None or AutoTokenizer is None:
            return
        if not self.model_path.exists():
            return

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_path)

        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        self.model.config.pad_token_id = self.tokenizer.pad_token_id
        self.model.eval()

    def build_prompt(self, question: str) -> str:
        question = question.strip()
        return f"{SYSTEM_PROMPT}\n\nسؤال: {question}\nالإجابة:"

    def answer(self, question: str, max_new_tokens: int = 240) -> str:
        if not question or not question.strip():
            raise ValueError("السؤال لا يمكن أن يكون فارغا.")

        private_answer = self._answer_from_private_knowledge(question)
        if private_answer:
            return private_answer

        if self.model is None or self.tokenizer is None:
            return (
                "لم يتم تحميل أوزان النموذج على الخادم، لذلك أعمل حاليا بطبقة المعرفة المحاسبية المدمجة.\n"
                "- أستطيع الإجابة عن الرواتب والسلف وفواتير البيع والشراء.\n"
                "- أستطيع شرح القيود والضريبة والمخزون والتقارير.\n"
                "- إذا سألت عن أكثر من موضوع سأجمع لك الإجابة في نقاط متعددة."
            )

        with torch.inference_mode():
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

    @staticmethod
    def _answer_from_private_knowledge(question: str) -> str | None:
        normalized_question = question.strip().lower()
        context_answer = _answer_from_financial_context(question)
        if context_answer:
            return context_answer

        matched_sections: list[str] = []
        for title, words, answer in ACCOUNTING_PATTERNS:
            if _contains_any(normalized_question, words):
                matched_sections.append(f"- {title}: {answer}")

        if matched_sections:
            if len(matched_sections) == 1:
                return matched_sections[0].removeprefix("- ").strip()
            return "إجابة مجمعة حسب المواضيع التي سألت عنها:\n" + "\n".join(matched_sections[:6])

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


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"{MODEL_NAME} جاهز.")
    print(ask("اشرح الرواتب والسلف والمبيعات والمشتريات"))
