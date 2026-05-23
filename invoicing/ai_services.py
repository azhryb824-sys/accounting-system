import base64
import json
import os
import re
from decimal import Decimal

import requests
from django.conf import settings
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from .models import Invoice, InvoiceItem, Item, PurchaseInvoice


PRIVATE_AI_URL = "http://127.0.0.1:8010/ask"
PRIVATE_AI_NAME = "نموذج عبدالرحمن المحاسبي"


def _private_ai_url():
    return (
        getattr(settings, "PRIVATE_ACCOUNTING_AI_URL", "")
        or os.environ.get("PRIVATE_ACCOUNTING_AI_URL", "")
        or PRIVATE_AI_URL
    ).strip()


def _private_ai_request(prompt, max_new_tokens=350, **extra_payload):
    max_new_tokens = min(int(max_new_tokens or 350), 900)
    payload = {
        "question": prompt,
        "max_new_tokens": max_new_tokens,
    }
    if "image_base64" in extra_payload:
        payload["image_base64"] = extra_payload["image_base64"]
        payload["media_type"] = extra_payload.get("media_type", "image/jpeg")
    try:
        response = requests.post(
            _private_ai_url(),
            data=json.dumps(payload, ensure_ascii=False, default=str),
            headers={"Content-Type": "application/json"},
            timeout=90,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "message": "تعذر الاتصال بنموذجك الخاص. تأكد أن خدمة accounting-ai تعمل على المنفذ 8010 أو اضبط PRIVATE_ACCOUNTING_AI_URL.",
            "raw": str(exc)[:1000],
        }

    if response.status_code >= 400:
        return {
            "ok": False,
            "message": f"تعذر الاتصال بنموذجك الخاص: {response.status_code}",
            "raw": response.text[:1000],
        }

    try:
        data = response.json()
    except ValueError:
        return {
            "ok": False,
            "message": "رد نموذجك الخاص ليس JSON صالحا.",
            "raw": response.text[:1000],
        }

    text = (data.get("answer") or data.get("text") or data.get("response") or "").strip()
    return {
        "ok": True,
        "text": text,
        "data": data.get("data"),
        "model": data.get("model") or PRIVATE_AI_NAME,
        "owner": data.get("owner") or "",
        "raw": data,
    }


def ai_configuration_status():
    return {
        "has_key": True,
        "key_name": "PRIVATE_ACCOUNTING_AI_URL",
        "model": PRIVATE_AI_NAME,
        "private_model": PRIVATE_AI_NAME,
        "private_url": _private_ai_url(),
        "uses_private_model": True,
        "accepted_names": ("PRIVATE_ACCOUNTING_AI_URL",),
    }


def _json_from_text(text):
    cleaned = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def branch_ai_context(branch_id):
    today = timezone.localdate()
    start = today.replace(day=1)
    invoices = Invoice.objects.filter(branch_id=branch_id)
    purchases = PurchaseInvoice.objects.filter(branch_id=branch_id)
    items = Item.objects.filter(branch_id=branch_id)
    month_invoices = invoices.filter(issue_date__date__range=[start, today])
    month_purchases = purchases.filter(issue_date__range=[start, today])
    return {
        "period": f"{start} إلى {today}",
        "sales_total": month_invoices.aggregate(total=Coalesce(Sum("total_with_vat"), Decimal("0")))["total"],
        "purchases_total": month_purchases.aggregate(total=Coalesce(Sum("total_with_vat"), Decimal("0")))["total"],
        "invoice_count": month_invoices.count(),
        "purchase_count": month_purchases.count(),
        "inventory_value": items.aggregate(total=Coalesce(Sum(F("quantity") * F("cost")), Decimal("0")))["total"],
        "low_stock_count": items.filter(quantity__lte=F("min_quantity"), is_active=True).count(),
        "low_stock_items": list(items.filter(quantity__lte=F("min_quantity"), is_active=True).values_list("name", flat=True)[:8]),
        "top_items": list(
            InvoiceItem.objects.filter(invoice__branch_id=branch_id)
            .values("item__name")
            .annotate(quantity=Coalesce(Sum("quantity"), Decimal("0")), total=Coalesce(Sum("line_total_with_vat"), Decimal("0")))
            .order_by("-total")[:6]
        ),
        "customers_count": invoices.values("customer_id").distinct().count(),
    }


def local_financial_insights(context):
    tips = []
    sales = context["sales_total"] or Decimal("0")
    purchases = context["purchases_total"] or Decimal("0")
    if sales <= 0:
        tips.append("لا توجد مبيعات مسجلة في الفترة الحالية. ابدأ بمراجعة إدخال الفواتير أو نشاط الفرع.")
    if purchases > sales and sales > 0:
        tips.append("المشتريات أعلى من المبيعات في الفترة الحالية؛ راجع المخزون البطيء وسياسة الشراء.")
    if context["low_stock_count"]:
        tips.append(f"يوجد {context['low_stock_count']} صنف عند حد التنبيه أو أقل، وأهمها: {', '.join(context['low_stock_items'])}.")
    if context["invoice_count"] and not context["customers_count"]:
        tips.append("توجد فواتير بدون تنوع واضح في العملاء؛ راجع بيانات العملاء وربطها بالفواتير.")
    if not tips:
        tips.append("المؤشرات الأساسية مستقرة حاليا. تابع التدفق النقدي والمخزون بشكل أسبوعي.")
    return tips


SYSTEM_HELP_PATTERNS = [
    (("كيف أبدأ", "استخدام النظام", "أستخدم النظام"), "ابدأ بتسجيل الدخول، ثم اختر الشركة والفرع، ثم أدخل العملاء والموردين والأصناف. بعد ذلك استخدم فواتير البيع والشراء، وراجع النتائج من لوحة التحكم ومركز التقارير."),
    (("اختيار الشركة", "اختيار الفرع", "الشركة والفرع"), "افتح اختيار الشركة والفرع من القائمة الجانبية، اختر الشركة ثم الفرع، ثم احفظ. معظم بيانات النظام تعتمد على الفرع المختار."),
    (("فاتورة بيع", "إضافة بيع", "اضافة بيع"), "لإضافة فاتورة بيع افتح فواتير البيع ثم إضافة فاتورة بيع، اختر العميل وطريقة الدفع، أضف الأصناف والكميات والأسعار، ثم احفظ ورحل الفاتورة عند الحاجة."),
    (("فاتورة شراء", "إضافة شراء", "اضافة شراء"), "لإضافة فاتورة شراء افتح فواتير الشراء ثم إضافة فاتورة شراء، اختر المورد، أضف الأصناف والكميات والأسعار، ثم احفظ. النظام يحدث المخزون ويربط القيد عند الترحيل."),
    (("فاتورة مصورة", "صورة فاتورة", "رفع فاتورة", "ocr"), "لرفع فاتورة مصورة افتح إضافة فاتورة بالنموذج الخاص، ارفع صورة واضحة أو PDF نصي، ثم راجع البيانات المستخرجة قبل الحفظ."),
    (("المخزون", "إضافة صنف", "اضافة صنف"), "لإضافة صنف افتح المخزون ثم إضافة صنف، أدخل الاسم والتكلفة وسعر البيع والكمية وحد التنبيه، ثم احفظ."),
    (("عميل", "العملاء"), "لإضافة عميل افتح العملاء ثم إضافة عميل، أدخل بيانات العميل واحفظه لاستخدامه في فواتير البيع."),
    (("مورد", "الموردين"), "لإضافة مورد افتح الموردين ثم إضافة مورد، أدخل بيانات المورد واحفظه لاستخدامه في فواتير الشراء."),
    (("قيد", "القيود اليومية"), "لإضافة قيد افتح القيود اليومية ثم إضافة قيد، أدخل التاريخ والوصف وسطور المدين والدائن، وتأكد من توازن القيد قبل الحفظ."),
    (("راتب", "الرواتب"), "لاستخدام الرواتب افتح رواتب الموظفين. أنشئ الراتب ثم اعتمده لإنشاء قيد الاستحقاق، وبعد ذلك ادفعه لإنشاء قيد الصرف."),
    (("سلفة", "السلف"), "لإضافة سلفة افتح سلف الموظفين ثم إضافة سلفة. اختر الموظف والمبلغ والتاريخ وطريقة الصرف، ثم احفظ."),
    (("القفل الشهري", "قفل شهر"), "للقفل الشهري افتح القفل الشهري ثم إضافة قفل، واختر الشركة والسنة والشهر. بعد القفل يمنع النظام الترحيل داخل الشهر."),
    (("غير مرحلة", "العمليات غير المرحلة"), "لمراجعة العمليات غير المرحلة افتح مركز التقارير ثم تقرير العمليات غير المرحلة. ستظهر العمليات التي لا ترتبط بقيود محاسبية."),
    (("المساعد الصوتي", "الدردشة الصوتية", "تحدث"), "لاستخدام المساعد الصوتي افتح المساعد المالي واضغط تحدث، قل طلبك، ثم سيحلل النظام الكلام ويعرض الإجابة أو رابط الصفحة المناسبة."),
]


LOCAL_GREETING_PATTERNS = (
    "السلام عليكم",
    "سلام عليكم",
    "مرحبا",
    "أهلا",
    "اهلا",
    "هلا",
    "صباح الخير",
    "مساء الخير",
    "hello",
    "hi",
)

LOCAL_GENERAL_CHAT = [
    (
        ("كيف حالك", "كيفك", "كيف الحال", "عامل ايه", "عامل شنو", "اخبارك"),
        "أنا بخير وبحماس للعمل معك. جاهز أراجع الأرقام، أشرح لك أي مفهوم محاسبي، أو أساعدك خطوة بخطوة داخل النظام. أعطني السؤال وسأجعله واضحا ومفيدا بدون تعقيد.",
    ),
    (
        ("شكرا", "شكرًا", "يعطيك العافية", "الله يعطيك العافية", "ممتاز", "تمام"),
        "العفو، هذا من ذوقك. خلينا نكمل الشغل بهدوء: إذا عندك فاتورة، قيد، راتب، سلفة، أو سؤال محاسبي عام أرسله لي وسأرتبه لك بشكل واضح.",
    ),
    (
        ("من أنت", "مين انت", "من انت", "عرف نفسك", "ما دورك"),
        f"أنا {PRIVATE_AI_NAME}، مساعد محاسبي ودود داخل النظام. أساعدك في فهم المحاسبة، قراءة مؤشرات شركتك، متابعة الفواتير والمخزون والرواتب والسلف، وتوجيهك للخطوة المناسبة داخل النظام.",
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

LOCAL_MULTILINGUAL_HELP = [
    (("كيف اضيف فاتورة", "كيف أضيف فاتورة", "ابغى اضيف فاتورة", "ابي اضيف فاتورة"), "لإضافة فاتورة: إذا كانت بيع افتح فواتير البيع ثم إضافة فاتورة بيع. وإذا كانت شراء افتح فواتير الشراء ثم إضافة فاتورة شراء. اختر العميل أو المورد، أضف الأصناف والكميات والأسعار، ثم احفظ."),
    (("عايز اضيف فاتورة", "داير اضيف فاتورة", "اضيف فاتورة كيف"), "عشان تضيف فاتورة: لو فاتورة بيع افتح فواتير البيع ثم إضافة فاتورة بيع. ولو فاتورة شراء افتح فواتير الشراء ثم إضافة فاتورة شراء. اختار العميل أو المورد وأدخل الأصناف والكميات والأسعار، وبعدها احفظ."),
    (("انوائس کیسے", "انوائس بنانا", "invoice kaise", "بل کیسے", "رسید کیسے"), "Invoice بنانے کے لیے: Sales Invoice کے لیے فواتير البيع ثم إضافة فاتورة بيع کھولیں، Purchase Invoice کے لیے فواتير الشراء ثم إضافة فاتورة شراء کھولیں۔ Customer یا Supplier منتخب کریں، items, quantities اور prices شامل کریں، پھر save کریں۔"),
    (("ইনভয়েস", "চালান", "invoice kivabe", "invoice কিভাবে", "বিল কিভাবে"), "ইনভয়েস যোগ করতে: Sales invoice হলে فواتير البيع ثم إضافة فاتورة بيع খুলুন, Purchase invoice হলে فواتير الشراء ثم إضافة فاتورة شراء খুলুন। Customer বা Supplier নির্বাচন করুন, items, quantities এবং prices লিখে save করুন।"),
]

LOCAL_ACCOUNTING_CONCEPTS = [
    (("مدين", "دائن"), "المدين والدائن هما طرفا القيد. المدين تزيد فيه الأصول والمصروفات غالبا، والدائن تزيد فيه الالتزامات والإيرادات وحقوق الملكية غالبا. يجب أن يتساوى مجموع المدين مع مجموع الدائن."),
    (("الأصول", "اصل", "أصل"), "الأصول هي موارد تملكها المنشأة أو تسيطر عليها مثل النقدية والبنك والعملاء والمخزون. غالبا تزيد في الجانب المدين."),
    (("الخصوم", "الالتزامات"), "الخصوم أو الالتزامات هي مبالغ مستحقة على المنشأة مثل الموردين والقروض والرواتب المستحقة. غالبا تزيد في الجانب الدائن."),
    (("حقوق الملكية", "رأس المال", "راس المال"), "حقوق الملكية تمثل حق المالك في المنشأة بعد طرح الالتزامات من الأصول. تشمل رأس المال والأرباح المحتجزة والمسحوبات."),
    (("الإيرادات", "الايرادات", "إيراد"), "الإيرادات هي ما تحققه المنشأة من بيع السلع أو تقديم الخدمات. في العادة تسجل دائنة."),
    (("المصروفات", "مصروف"), "المصروفات هي تكاليف تشغيل النشاط مثل الرواتب والإيجار والمصاريف الإدارية. في العادة تسجل مدينة وتخفض الربح."),
    (("القيد المزدوج", "double entry"), "القيد المزدوج يعني تسجيل كل عملية بطرف مدين وطرف دائن على الأقل، ولا يكون القيد صحيحا إلا إذا توازن الطرفان."),
    (("ميزان المراجعة",), "ميزان المراجعة يجمع أرصدة الحسابات للتأكد من توازن المدين والدائن، لكنه لا يضمن عدم وجود أخطاء تصنيف أو ترحيل."),
    (("قائمة الدخل", "الربح والخسارة"), "قائمة الدخل تعرض الإيرادات والمصروفات خلال فترة معينة للوصول إلى صافي الربح أو الخسارة."),
    (("المركز المالي", "الميزانية"), "قائمة المركز المالي تعرض الأصول والخصوم وحقوق الملكية. معادلتها: الأصول = الخصوم + حقوق الملكية."),
    (("التدفق النقدي", "السيولة"), "التدفق النقدي يوضح حركة دخول وخروج النقد، وهو مهم لأن الربح لا يعني دائما توفر السيولة."),
    (("ضريبة القيمة المضافة", "vat"), "ضريبة القيمة المضافة تظهر في المبيعات كضريبة مخرجات وفي المشتريات كضريبة مدخلات، وصافي المستحق هو الفرق بينهما غالبا."),
]


def local_greeting_or_concept_answer(question):
    normalized = (question or "").strip().lower()
    for words, answer in LOCAL_GENERAL_CHAT:
        if any(word in normalized for word in words):
            return answer
    if any(word in normalized for word in ("كيفك", "وش", "ابشر", "الله يعطيك")) and any(word in normalized for word in LOCAL_GREETING_PATTERNS):
        return "وعليكم السلام ورحمة الله وبركاته، حيّاك الله. أبشر، أنا معك كمساعد محاسبي ودود داخل النظام. أقدر أساعدك في الفواتير والقيود والرواتب والسلف والتقارير وشرح المفاهيم المحاسبية بطريقة بسيطة ومفيدة."
    if any(word in normalized for word in ("يا زول", "كيفنك", "عامل شنو", "مرحبتين")):
        return "وعليكم السلام، مرحبتين بيك يا زول. أنا مساعدك المحاسبي في النظام، بقدر أساعدك في الفواتير والقيود والرواتب والسلف والتقارير وشرح المحاسبة بطريقة واضحة."
    if any(word in normalized for word in ("السلام علیکم", "آداب", "خوش آمدید", "ہیلو")):
        return "وعلیکم السلام، خوش آمدید۔ میں آپ کا اکاؤنٹنگ اسسٹنٹ ہوں۔ میں سسٹم کے استعمال، انوائسز، جرنل انٹریز، تنخواہوں، ایڈوانسز، رپورٹس اور اکاؤنٹنگ تصورات میں مدد کر سکتا ہوں۔"
    if any(word in normalized for word in ("আসসালামু", "সালাম", "নমস্কার", "হ্যালো", "স্বাগতম")):
        return "ওয়ালাইকুম আসসালাম, স্বাগতম। আমি আপনার হিসাবরক্ষণ সহকারী। আমি সিস্টেম ব্যবহার, ইনভয়েস, জার্নাল এন্ট্রি, বেতন, অগ্রিম, রিপোর্ট এবং হিসাববিজ্ঞানের ধারণা বুঝতে সাহায্য করতে পারি।"
    if any(word in normalized for word in LOCAL_GREETING_PATTERNS):
        return "وعليكم السلام ورحمة الله وبركاته، أهلا وسهلا بك. نورت النظام. أنا مساعدك المحاسبي داخل النظام، أستطيع مساعدتك في استخدام النظام وشرح المفاهيم المحاسبية وتحليل البيانات."
    multilingual_matches = [answer for words, answer in LOCAL_MULTILINGUAL_HELP if any(word.lower() in normalized for word in words)]
    if multilingual_matches:
        return "\n".join(f"- {answer}" for answer in dict.fromkeys(multilingual_matches))
    matches = [answer for words, answer in LOCAL_ACCOUNTING_CONCEPTS if any(word.lower() in normalized for word in words)]
    if not matches:
        return ""
    return "\n".join(f"- {answer}" for answer in dict.fromkeys(matches))


def local_system_usage_answer(question):
    normalized = (question or "").strip().lower()
    matches = [answer for words, answer in SYSTEM_HELP_PATTERNS if any(word.lower() in normalized for word in words)]
    if not matches:
        return ""
    return "\n".join(f"- {answer}" for answer in dict.fromkeys(matches))


def generate_financial_insights(branch_id):
    context = branch_ai_context(branch_id)
    fallback = local_financial_insights(context)
    prompt = (
        "أنت نموذج عبدالرحمن المحاسبي داخل نظام محاسبي سعودي. "
        "حلل بيانات الفرع التالية بالعربية وقدم 5 توصيات عملية قصيرة دون اختراع أرقام غير موجودة:\n"
        f"{json.dumps(context, ensure_ascii=False, default=str)}"
    )
    result = _private_ai_request(prompt, max_new_tokens=650, task="financial_insights", context=context)
    if not result.get("ok") or not result.get("text"):
        return {
            "ok": True,
            "source": "local",
            "context": context,
            "tips": fallback,
            "warning": result.get("message"),
        }

    tips = [line.strip(" -•\t") for line in result["text"].splitlines() if line.strip()]
    return {"ok": True, "source": "private", "context": context, "tips": tips[:7] or fallback}


def answer_financial_question(branch_id, question):
    context = branch_ai_context(branch_id)
    usage_answer = local_system_usage_answer(question)
    prompt = (
        "أجب بالعربية كمساعد مالي خاص داخل نظام محاسبي. استخدم بيانات الفرع المتاحة فقط، "
        "وإذا لم تكف البيانات فاذكر ذلك بوضوح. لا تقدم استشارة قانونية نهائية.\n"
        f"بيانات الفرع: {json.dumps(context, ensure_ascii=False, default=str)}\n"
        f"سؤال المستخدم: {question}"
    )
    result = _private_ai_request(prompt, max_new_tokens=750, task="financial_question", context=context)
    if not result.get("ok") or not result.get("text"):
        return {
            "ok": True,
            "source": "local",
            "answer": "تعذر الاتصال بالنموذج الخاص حاليا. بناء على البيانات الحالية: " + " ".join(local_financial_insights(context)),
            "context": context,
            "warning": result.get("message"),
        }

    return {"ok": True, "source": "private", "answer": result["text"], "context": context}


_model_answer_financial_question = answer_financial_question


def answer_financial_question(branch_id, question):
    local_direct_answer = local_greeting_or_concept_answer(question)
    usage_answer = local_system_usage_answer(question)
    result = _model_answer_financial_question(branch_id, question)
    answer_text = result.get("answer") or result.get("message") or ""
    if local_direct_answer and (
        result.get("source") == "local"
        or "قراءة النموذج للبيانات الحالية" in answer_text
        or "تعذر الاتصال" in answer_text
        or "طھط¹ط°ط±" in answer_text
    ):
        result["answer"] = local_direct_answer
        result["source"] = "local"
        return result
    if local_direct_answer and local_direct_answer not in answer_text:
        answer_text = f"{local_direct_answer}\n\n{answer_text}".strip()
    if usage_answer and (
        result.get("source") == "local"
        or "قراءة النموذج للبيانات الحالية" in answer_text
        or "تعذر الاتصال" in answer_text
        or "طھط¹ط°ط±" in answer_text
    ):
        result["answer"] = usage_answer
        result["source"] = "local"
        return result
    if usage_answer and usage_answer not in answer_text:
        answer_text = f"{usage_answer}\n\n{answer_text}".strip()
    result["answer"] = answer_text
    return result


ASSISTANT_ACTIONS = [
    {
        "name": "dashboard",
        "title": "لوحة التحكم",
        "url_name": "dashboard",
        "keywords": ("لوحة التحكم", "الرئيسية", "الداشبورد", "dashboard"),
        "description": "فتح لوحة التحكم العامة.",
    },
    {
        "name": "reports",
        "title": "مركز التقارير",
        "url_name": "reports_center",
        "keywords": ("التقارير", "تقرير", "reports", "كشف"),
        "description": "فتح مركز التقارير.",
    },
    {
        "name": "payroll_report",
        "title": "كشف الرواتب",
        "url_name": "payroll_report",
        "keywords": ("كشف الرواتب", "تقرير الرواتب", "مسير الرواتب"),
        "description": "فتح تقرير كشف الرواتب.",
    },
    {
        "name": "advance_report",
        "title": "كشف السلف",
        "url_name": "advance_report",
        "keywords": ("كشف السلف", "تقرير السلف", "سلف الموظفين"),
        "description": "فتح تقرير السلف.",
    },
    {
        "name": "unposted",
        "title": "العمليات غير المرحلة",
        "url_name": "unposted_operations_report",
        "keywords": ("غير مرحلة", "غير المرحله", "عمليات غير مرحلة", "لم ترحل"),
        "description": "فتح تقرير العمليات غير المرحلة محاسبيا.",
    },
    {
        "name": "sales",
        "title": "فواتير البيع",
        "url_name": "invoice_list",
        "keywords": ("فواتير البيع", "المبيعات", "بيع", "العملاء"),
        "description": "فتح قائمة فواتير البيع.",
    },
    {
        "name": "add_sale",
        "title": "إضافة فاتورة بيع",
        "url_name": "invoice_create",
        "keywords": ("أضف فاتورة بيع", "اضافة فاتورة بيع", "فاتورة بيع جديدة", "أنشئ فاتورة بيع"),
        "description": "فتح نموذج إضافة فاتورة بيع.",
    },
    {
        "name": "purchases",
        "title": "فواتير الشراء",
        "url_name": "purchase_list",
        "keywords": ("فواتير الشراء", "المشتريات", "شراء", "الموردين"),
        "description": "فتح قائمة فواتير الشراء.",
    },
    {
        "name": "add_purchase",
        "title": "إضافة فاتورة شراء",
        "url_name": "purchase_add",
        "keywords": ("أضف فاتورة شراء", "اضافة فاتورة شراء", "فاتورة شراء جديدة", "أنشئ فاتورة شراء"),
        "description": "فتح نموذج إضافة فاتورة شراء.",
    },
    {
        "name": "ai_invoice",
        "title": "إضافة فاتورة بالذكاء الاصطناعي",
        "url_name": "ai_invoice_import",
        "keywords": ("فاتورة مصورة", "صورة فاتورة", "قراءة فاتورة", "فاتورة بالذكاء", "ocr"),
        "description": "فتح صفحة رفع فاتورة مصورة لاستخراجها بالذكاء الاصطناعي.",
    },
    {
        "name": "inventory",
        "title": "المخزون",
        "url_name": "inventory_list",
        "keywords": ("المخزون", "الأصناف", "الصنف", "المنتجات"),
        "description": "فتح قائمة المخزون والأصناف.",
    },
    {
        "name": "employees",
        "title": "الموظفون",
        "url_name": "employee_list",
        "keywords": ("الموظفين", "الموظفون", "موظف"),
        "description": "فتح قائمة الموظفين.",
    },
    {
        "name": "salaries",
        "title": "رواتب الموظفين",
        "url_name": "salary_list",
        "keywords": ("رواتب الموظفين", "مسير الرواتب", "الرواتب", "راتب"),
        "description": "فتح صفحة رواتب الموظفين.",
    },
    {
        "name": "advances",
        "title": "سلف الموظفين",
        "url_name": "advance_list",
        "keywords": ("السلف", "سلفة", "سلف الموظفين"),
        "description": "فتح صفحة سلف الموظفين.",
    },
    {
        "name": "journal",
        "title": "القيود اليومية",
        "url_name": "journal_list",
        "keywords": ("القيود", "قيد", "اليومية", "دفتر اليومية"),
        "description": "فتح قائمة القيود اليومية.",
    },
    {
        "name": "add_journal",
        "title": "إضافة قيد يومية",
        "url_name": "journal_add",
        "keywords": ("أضف قيد", "اضافة قيد", "قيد جديد", "أنشئ قيد"),
        "description": "فتح نموذج إضافة قيد يومية.",
    },
]


def _safe_reverse(url_name):
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return ""


def analyze_and_route_user_request(branch_id, request_text):
    text = (request_text or "").strip()
    normalized = text.lower()
    matched = []
    for action in ASSISTANT_ACTIONS:
        score = sum(len(keyword) for keyword in action["keywords"] if keyword.lower() in normalized)
        if score:
            url = _safe_reverse(action["url_name"])
            if url:
                matched.append({**action, "score": score, "url": url})

    matched.sort(key=lambda row: row["score"], reverse=True)
    primary = matched[0] if matched else None
    wants_open = any(word in normalized for word in ("افتح", "اذهب", "روح", "انتقل", "اعرض", "أظهر", "نفذ", "ابدأ"))
    wants_create = any(word in normalized for word in ("أضف", "اضف", "أنشئ", "انشئ", "سجل", "ادخل"))

    financial_answer = answer_financial_question(branch_id, text)
    answer_text = financial_answer.get("answer") or financial_answer.get("message") or ""

    if primary:
        action_text = f"فهمت طلبك: {primary['description']}"
        if wants_create:
            action_text += " يمكنك إدخال البيانات من النموذج ثم الحفظ."
        elif wants_open:
            action_text += " سأفتح الصفحة المناسبة."
        else:
            action_text += " وجدت صفحة مناسبة لهذا الطلب."
        answer_text = f"{action_text}\n\n{answer_text}".strip()

    return {
        "ok": True,
        "answer": answer_text,
        "source": financial_answer.get("source", "local"),
        "action": {
            "type": "navigate" if primary else "answer",
            "title": primary["title"] if primary else "",
            "url": primary["url"] if primary else "",
            "auto_open": bool(primary and wants_open),
        },
        "suggestions": [
            {"title": row["title"], "url": row["url"], "description": row["description"]}
            for row in matched[:4]
        ],
        "context": financial_answer.get("context", {}),
    }


def extract_invoice_from_image(uploaded_file):
    content = uploaded_file.read()
    image_b64 = base64.b64encode(content).decode("utf-8")
    media_type = uploaded_file.content_type or "image/jpeg"
    prompt = (
        "استخرج بيانات فاتورة شراء من الصورة. أعد JSON فقط دون شرح بالمفاتيح التالية: "
        "supplier_name, invoice_number, issue_date بصيغة YYYY-MM-DD, subtotal, vat, total, "
        "items كقائمة عناصر، وكل عنصر يحتوي name, quantity, unit_price. "
        "استخدم الأرقام فقط للقيم المالية والكميات."
    )
    result = _private_ai_request(
        prompt,
        max_new_tokens=300,
        task="invoice_image_extraction",
        image_base64=image_b64,
        media_type=media_type,
    )
    if not result.get("ok"):
        return result

    if isinstance(result.get("data"), dict):
        if result["data"].get("error"):
            return {
                "ok": False,
                "message": result["data"]["error"],
                "raw": result["data"],
            }
        return {"ok": True, "data": result["data"]}

    try:
        extracted = _json_from_text(result.get("text") or "")
    except (json.JSONDecodeError, TypeError):
        return {
            "ok": False,
            "message": "تعذر قراءة نتيجة نموذجك الخاص كبيانات فاتورة منظمة.",
            "raw": result.get("text", ""),
        }
    return {"ok": True, "data": extracted}


def match_invoice_items(branch_id, extracted_items):
    matched = []
    existing = list(Item.objects.filter(branch_id=branch_id, is_active=True))
    for row in extracted_items or []:
        name = (row.get("name") or "").strip()
        item = next((x for x in existing if x.name.strip().lower() == name.lower()), None)
        if not item:
            item = next((x for x in existing if name and (name.lower() in x.name.lower() or x.name.lower() in name.lower())), None)
        matched.append({
            "source_name": name,
            "item": item,
            "quantity": Decimal(str(row.get("quantity") or 1)),
            "unit_price": Decimal(str(row.get("unit_price") or 0)),
        })
    return matched
