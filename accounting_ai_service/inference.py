import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from difflib import SequenceMatcher

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


MODEL_NAME = "نموذج عبدالرحمن المحاسبي"
MODEL_OWNER = "عبدالرحمن"
MODEL_PATH = Path(__file__).resolve().parent / "models" / "my_model"

SYSTEM_PROMPT = f"""
أنت {MODEL_NAME}، مساعد ذكاء اصطناعي خاص بـ {MODEL_OWNER}.
تجيب بالعربية بوضوح واختصار، وتركز على المحاسبة والفواتير والمخزون والقيود اليومية والرواتب والسلف.
إذا كانت البيانات غير كافية فاذكر ذلك بوضوح ولا تخترع أرقاما.
""".strip()

PRIVATE_KNOWLEDGE = {
    "الفاتورة الضريبية": "الفاتورة الضريبية مستند رسمي يوضح بيانات البائع والمشتري والسلع أو الخدمات والمبلغ وضريبة القيمة المضافة، وتستخدم لإثبات عملية البيع محاسبيا وضريبيا.",
    "المخزون عند البيع": "عند البيع تنخفض كمية الصنف من المخزون بمقدار الكمية المباعة، ويظهر أثر العملية في تكلفة البضاعة المباعة والإيراد حسب طريقة التسجيل المحاسبي.",
    "قيد اليومية": "قيد اليومية هو تسجيل محاسبي لكل عملية مالية، ويجب أن يحتوي على طرف مدين وطرف دائن بحيث يتساوى مجموع المدين مع مجموع الدائن.",
    "المصروفات": "المصروفات تقلل صافي الربح لأنها تمثل تكلفة تحملتها المنشأة للحصول على الإيراد أو تشغيل النشاط.",
    "الدفع النقدي": "الدفع النقدي يعني أن قيمة العملية تم تحصيلها مباشرة وقت البيع أو تقديم الخدمة، بدلا من تسجيلها كذمة على العميل.",
    "البيع الآجل": "البيع الآجل يعني بيع سلعة أو خدمة الآن مع تأجيل تحصيل المبلغ، ويظهر عادة ضمن حسابات العملاء أو الذمم المدينة.",
    "ضريبة القيمة المضافة": "ضريبة القيمة المضافة ضريبة غير مباشرة تظهر في المبيعات كضريبة مخرجات، وفي المشتريات كضريبة مدخلات، ويحسب صافي الالتزام من الفرق بينهما.",
    "حد التنبيه": "حد التنبيه في المخزون هو مستوى تحدده للصنف حتى ينبهك النظام عند انخفاض الكمية، مما يساعد على إعادة الطلب في الوقت المناسب.",
    "من أنت": f"أنا {MODEL_NAME}، مساعد ذكاء اصطناعي محاسبي خاص بـ {MODEL_OWNER} ومصمم لمساعدتك في الفواتير والمخزون والقيود والرواتب والسلف.",
}

ACCOUNTING_PATTERNS = [
    (
        ("راتب", "رواتب", "مسير", "موظف", "الموظفين"),
        "الرواتب في النظام تمر بمرحلتين: اعتماد الراتب ثم دفعه. عند الاعتماد يتم إثبات مصروف الرواتب مقابل رواتب مستحقة، وإذا وُجد خصم سلفة يتم تخفيض حساب سلف الموظفين. عند الدفع يتم تخفيض الرواتب المستحقة مقابل الصندوق أو البنك.",
    ),
    (
        ("سلفة", "سلف", "advance"),
        "سلفة الموظف تسجل كأصل على حساب سلف الموظفين عند صرفها. وعند خصمها من الراتب ينخفض رصيد السلفة ويظهر الخصم ضمن قيد استحقاق الراتب حتى تصبح السلفة مسددة بالكامل.",
    ),
    (
        ("فاتورة بيع", "مبيعات", "بيع", "عميل"),
        "فاتورة البيع تؤثر على الإيرادات وضريبة القيمة المضافة. إذا كانت نقدية أو بطاقة أو تحويل يكون الطرف المدين الصندوق أو البنك، وإذا كانت آجلة يكون الطرف المدين العملاء. كما ينخفض المخزون وتثبت تكلفة البضاعة المباعة عند الترحيل.",
    ),
    (
        ("فاتورة شراء", "مشتريات", "شراء", "مورد"),
        "فاتورة الشراء تزيد المخزون وتثبت ضريبة المدخلات، ويكون الطرف الدائن غالبا الموردين إذا لم يتم السداد مباشرة. ويجب التأكد من عدم تكرار تحديث المخزون عند إدخال بنود الشراء.",
    ),
    (
        ("قيد", "قيود", "مدين", "دائن"),
        "أي عملية محاسبية صحيحة يجب أن تنتج قيدا متوازنا: مجموع المدين يساوي مجموع الدائن. إذا لم يتوازن القيد فهناك خطأ في الحسابات أو في اختيار الحسابات المرتبطة بالعملية.",
    ),
    (
        ("تقرير", "تقارير", "تحليل", "مؤشرات"),
        "ابدأ بقراءة المبيعات والمشتريات وقيمة المخزون والرواتب والسلف المفتوحة. أهم التنبيهات تكون عند زيادة المشتريات عن المبيعات، ارتفاع السلف المفتوحة، انخفاض المخزون عن حد التنبيه، أو وجود عمليات غير مرحلة محاسبيا.",
    ),
]


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word.lower() in text for word in words)


def _extract_json_object(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _money(value) -> float:
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

    lines.append("الأولوية المقترحة: راجع العمليات غير المرحلة، ثم المخزون، ثم التحصيل والسلف والرواتب.")
    return "\n".join(lines)


class PrivateAccountingModel:
    def __init__(self, model_path: Path = MODEL_PATH):
        self.model_path = Path(model_path)
        self.tokenizer = None
        self.model = None
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

    @torch.inference_mode()
    def answer(self, question: str, max_new_tokens: int = 120) -> str:
        if not question or not question.strip():
            raise ValueError("السؤال لا يمكن أن يكون فارغا.")

        private_answer = self._answer_from_private_knowledge(question)
        if private_answer:
            return private_answer

        if self.model is None or self.tokenizer is None:
            return (
                "لم يتم تحميل أوزان النموذج على الخادم، لذلك أعمل حاليا بطبقة المعرفة المحاسبية المدمجة. "
                "اسأل عن الرواتب، السلف، فواتير البيع والشراء، القيود، الضريبة، المخزون أو التقارير."
            )

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

        for words, answer in ACCOUNTING_PATTERNS:
            if _contains_any(normalized_question, words):
                return answer

        best_key = None
        best_score = 0.0
        for key in PRIVATE_KNOWLEDGE:
            normalized_key = key.lower()
            if normalized_key in normalized_question:
                return PRIVATE_KNOWLEDGE[key]

            score = SequenceMatcher(None, normalized_key, normalized_question).ratio()
            if score > best_score:
                best_key = key
                best_score = score

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


def ask(question: str, max_new_tokens: int = 120) -> str:
    return get_model().answer(question, max_new_tokens=max_new_tokens)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"{MODEL_NAME} جاهز.")
    print(ask("ما هي الفاتورة الضريبية؟"))
