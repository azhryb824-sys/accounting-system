import base64
import hashlib
import ast
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from html.parser import HTMLParser
from decimal import Decimal
from urllib.parse import quote_plus, urlparse

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, F, Sum
from django.db.models.functions import Coalesce
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from core.access import user_companies
from core.models import Branch, Employee, EmployeeAdvance, JournalEntry, JournalEntryLine, SalaryRecord
from .models import AIInteractionLearning, AIKnowledgeEntry, AIKnowledgeSource, Customer, Invoice, InvoiceItem, Item, PurchaseInvoice, PurchaseItem, Quote, QuoteItem, Supplier, Tax
from .zatca import prepare_zatca_payload


PRIVATE_AI_URL = "http://127.0.0.1:8010/ask"
PRIVATE_AI_NAME = "نموذج عبدالرحمن المحاسبي"


PROFESSIONAL_ASSISTANT_RULES = """
أنت مساعد محاسبي احترافي داخل نظام محاسبة عربي. التزم بالقواعد التالية:
- ابدأ برد ودود مختصر يناسب سياق السؤال، بدون مبالغة.
- حلل نية المستخدم: سؤال عام، شرح محاسبي، سؤال عن بيانات الشركة، أو طلب تنفيذ داخل النظام.
- لا تخترع أرقاما. استخدم فقط البيانات المرسلة لك، واذكر بوضوح عندما تكون البيانات غير كافية.
- احترم الصلاحيات والفروع، ولا تطلب من المستخدم تجاوزها.
- اشرح المفاهيم المحاسبية بلغة سهلة مع مثال صغير عند الحاجة.
- قدم خطوات عملية تالية من داخل النظام.
- اجعل الإجابة مرتبة ومباشرة ومفيدة.
- أجب عن الأسئلة العادية والعلمية والثقافية كتابة وصوتا، واستخدم البحث المجاني الموثوق عند الحاجة إذا لم تكن الإجابة من بيانات النظام.
- لا تقدم فتوى أو حكما شرعيا أو شرحا لمسائل الشريعة الإسلامية. إذا سأل المستخدم عن أمر شرعي، اعتذر بلطف ووجهه للتواصل مع أهل العلم الموثوقين، ويمكنك فقط مساعدته في الجانب المحاسبي أو الإداري غير الشرعي من السؤال.
""".strip()


SAUDI_MARKET_ADVICE_RULES = """
عند تقديم نصائح تجارية أو مالية للسوق السعودي:
- ركز على ضريبة القيمة المضافة، الالتزام بالفوترة الإلكترونية، ضبط التدفق النقدي، المخزون، التحصيل، وتسعير المنتجات.
- اربط النصيحة بمؤشرات عملية داخل النظام: المبيعات، المشتريات، المخزون، الفواتير غير المرحلة، العملاء، الموردين، والرواتب.
- قدم توصيات قابلة للتنفيذ خلال أسبوع، وليس كلاما عاما.
- إذا كان المستخدم يتكلم بلهجة سعودية أو سودانية أو بالأوردو، حافظ على لغة مفهومة قريبة منه بدون الإخلال بالدقة.
- لا تعتمد على أخبار أو أسعار سوق لحظية غير موجودة في بيانات النظام.
""".strip()


DIALECT_AND_VOICE_RULES = """
قواعد اللغة واللهجات:
- إذا استخدم المستخدم لهجة سعودية، افهم كلمات مثل: أبغى، أبي، وش، كم باقي، حاسب، تمم، شبكة، مدى، كاشير، خلص البيع.
- إذا استخدم المستخدم لهجة سودانية، افهم كلمات مثل: داير، عايز، الزول، القروش، الفاتورة دي، وريني، أضف لي.
- إذا استخدم المستخدم الأوردو، افهم أوامر البيع والفواتير مثل: bill banao, invoice banao, item add karo, kitna, qeemat, customer.
- أجب بنفس أسلوب المستخدم ما أمكن، لكن اجعل الأرقام والمصطلحات المحاسبية واضحة.
- لا تدعي أن الصوت هو صوت ChatGPT. استخدم نبرة عربية/أوردو واضحة وهادئة حسب الصوت المتاح في الجهاز.
""".strip()


WEB_RESEARCH_AND_ANALYSIS_RULES = """
قواعد الإجابة العامة والبحث:
- افهم نية السؤال أولا: تحية، شرح تعليمي، سؤال عن بيانات النظام، سؤال عام، أو سؤال يحتاج معلومة حديثة.
- إذا كان السؤال عاما أو علميا أو ثقافيا أو تقنيا ولا توجد إجابته داخل بيانات النظام، استخدم المصادر المفتوحة المتاحة ورتبها حسب الموثوقية.
- لا تخلط بيانات الشركة مع معلومات الإنترنت. بيانات النظام لها الأولوية عند سؤال المستخدم عن شركته أو فواتيره أو فرعه.
- عند استخدام الإنترنت: اعرض خلاصة مباشرة، ثم تحليل مختصر، ثم مصادر بروابط وتراخيص أو ملاحظات موثوقية.
- إذا كان الموضوع سريع التغير مثل الأخبار والأسعار والأنظمة والإصدارات، قل بوضوح إن المعلومة تحتاج مراجعة المصدر الرسمي الأحدث.
- لا تخترع مصادر أو أرقاما. إذا لم تجد مصدرا كافيا، قل ذلك واطلب من المستخدم تحديد المجال أو أعطه طريقة تحقق.
""".strip()


WORLD_CLASS_AI_RESPONSE_CONTRACT = """
معيار الجودة العالمي للإجابة:
- ابدأ من سؤال المستخدم لا من قالب جاهز؛ إذا كان السؤال قصيرا أو غامضا فاطلب التوضيح بدلا من التحليل العشوائي.
- افصل بوضوح بين: معلومة مؤكدة من النظام، معلومة من مصدر خارجي، واستنتاج تحليلي.
- في الأسئلة المالية: اذكر الأرقام المتاحة فقط، ثم اشرح ماذا تعني، ثم أعط إجراء عمليا قابلا للتنفيذ.
- في الأسئلة العامة: قدم جوابا مباشرا ثم سياقا مختصرا ثم مصادر أو ملاحظة تحقق.
- في الأسئلة عالية المخاطر أو المتغيرة: لا تجزم؛ اذكر حدود المعرفة ووجّه للمصدر الرسمي أو المختص.
- لا تكرر السؤال ولا تطل بلا فائدة. اجعل كل سطر يخدم قرارا أو فهما.
""".strip()


def _detect_user_language(text):
    text = text or ""
    lowered = text.lower()
    if any(term in lowered for term in ("in english", "بالانجليزي", "بالإنجليزي", "english please")):
        return "en"
    if any(term in lowered for term in ("بالعربي", "باللغة العربية", "in arabic")):
        return "ar"
    if any(term in lowered for term in ("بالأوردو", "بالاوردو", "in urdu")):
        return "ur"
    if any(term in lowered for term in ("بالبنغالي", "in bengali", "bangla")):
        return "bn"
    if re.search(r"[\u0980-\u09FF]", text):
        return "bn"
    if re.search(r"[پچژگٹڈڑںے]", text):
        return "ur"
    arabic_chars = len(re.findall(r"[\u0600-\u06FF]", text))
    latin_chars = len(re.findall(r"[A-Za-z]", text))
    arabic_words = len(re.findall(r"[\u0600-\u06FF]{2,}", text))
    latin_words = len(re.findall(r"[A-Za-z]{2,}", text))
    if arabic_chars and (arabic_chars >= latin_chars or arabic_words >= latin_words or re.match(r"\s*[\u0600-\u06FF]", text)):
        return "ar"
    if latin_chars:
        return "en"
    return "ar"


def _language_instruction(question):
    language = _detect_user_language(question)
    labels = {
        "ar": "Arabic",
        "en": "English",
        "ur": "Urdu",
        "bn": "Bengali",
    }
    return (
        f"Detected user language: {labels.get(language, 'Arabic')}. "
        "Reply in the same language as the user's latest question unless the user explicitly asks for another language."
    )


def _professional_prompt(task, question, context=None, extra=""):
    payload = {
        "task": task,
        "question": question,
        "context": context or {},
    }
    return (
        f"{PROFESSIONAL_ASSISTANT_RULES}\n\n{SAUDI_MARKET_ADVICE_RULES}\n\n{DIALECT_AND_VOICE_RULES}\n\n{WEB_RESEARCH_AND_ANALYSIS_RULES}\n\n{WORLD_CLASS_AI_RESPONSE_CONTRACT}\n\n{_language_instruction(question)}\n\n"
        f"المهمة والبيانات:\n{json.dumps(payload, ensure_ascii=False, default=str)}\n"
        f"{extra}".strip()
    )


AI_MANAGED_ENTITY_LABELS = {
    "customer": "العميل",
    "supplier": "المورد",
    "item": "الصنف",
    "tax": "الضريبة",
    "employee": "الموظف",
    "advance": "السلفة",
}

AI_MANAGED_FIELDS = {
    "customer": ["name"],
    "supplier": ["name"],
    "item": ["name", "cost", "selling_price", "quantity"],
    "tax": ["name", "rate"],
    "employee": ["name", "basic_salary"],
    "advance": ["employee", "amount"],
}

AI_INTENT_LABELS = {
    "create": "إضافة",
    "update": "تعديل",
    "delete": "حذف",
    "read": "عرض",
}

AI_FIELD_QUESTIONS = {
    "name": "ما الاسم؟",
    "cost": "ما تكلفة الصنف؟",
    "selling_price": "ما سعر البيع؟",
    "quantity": "ما الكمية الافتتاحية؟",
    "rate": "ما نسبة الضريبة؟",
    "employee": "ما اسم الموظف؟",
    "amount": "ما المبلغ؟",
    "basic_salary": "ما الراتب الأساسي؟",
    "target": "ما اسم السجل الذي تريد تعديله أو حذفه؟",
    "field": "ما الحقل الذي تريد تعديله؟ مثل الاسم أو التكلفة أو سعر البيع أو الكمية.",
    "value": "ما القيمة الجديدة؟",
}


def _private_ai_url():
    return (
        getattr(settings, "PRIVATE_ACCOUNTING_AI_URL", "")
        or os.environ.get("PRIVATE_ACCOUNTING_AI_URL", "")
        or PRIVATE_AI_URL
    ).strip()


def _private_ai_headers():
    headers = {"Content-Type": "application/json"}
    api_key = (
        getattr(settings, "PRIVATE_ACCOUNTING_AI_API_KEY", "")
        or os.environ.get("PRIVATE_ACCOUNTING_AI_API_KEY", "")
    ).strip()
    if api_key:
        headers["X-Accounting-AI-Key"] = api_key
    return headers


def _private_ai_request(prompt, max_new_tokens=350, **extra_payload):
    max_new_tokens = min(int(max_new_tokens or 420), 1800)
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
            headers=_private_ai_headers(),
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


def _normalize_ai_text(text):
    return (text or "").strip().lower()


def _extract_decimal(text):
    match = re.search(r"(-?\d+(?:[.,]\d+)?)", text or "")
    if not match:
        return None
    return Decimal(match.group(1).replace(",", "."))


def _detect_ai_intent(text):
    normalized = _normalize_ai_text(text)
    if any(word in normalized for word in ("اضف", "أضف", "انشئ", "أنشئ", "سجل", "ادخل", "إضافة")):
        return "create"
    if any(word in normalized for word in ("احذف", "حذف", "امسح", "ازل", "أزل")):
        return "delete"
    if any(word in normalized for word in ("عدل", "تعديل", "غيّر", "غير", "حدث", "تحديث")):
        return "update"
    if any(word in normalized for word in ("اعرض", "عرض", "اسمع", "اقرأ", "اقرا", "ما هي", "ما هو")) or re.search(r"(^|\s)كم(\s|$)", normalized):
        return "read"
    return ""


def _detect_ai_entity(text):
    normalized = _normalize_ai_text(text)
    if any(word in normalized for word in ("عميل", "العميل", "عملاء", "زبون")):
        return "customer"
    if any(word in normalized for word in ("مورد", "المورد", "موردين")):
        return "supplier"
    if any(word in normalized for word in ("صنف", "الصنف", "منتج", "مخزون", "باركود")):
        return "item"
    if any(word in normalized for word in ("سلفة", "السلفة", "advance")):
        return "advance"
    if any(word in normalized for word in ("ضريبة", "tax", "vat")):
        return "tax"
    if any(word in normalized for word in ("موظف", "الموظف", "عامل", "employee", "staff")):
        return "employee"
    return ""


def _strip_command_words(text):
    cleaned = re.sub(
        r"(اضف|أضف|انشئ|أنشئ|سجل|ادخل|إضافة|عدل|تعديل|غيّر|غير|حدث|تحديث|احذف|حذف|امسح|ازل|أزل|عميل|العميل|عملاء|زبون|مورد|المورد|موردين|صنف|الصنف|منتج|مخزون|باسم|اسمه|اسمها|اسم|اسمو|اسمه)",
        " ",
        text or "",
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .،")
    return cleaned


def _extract_ai_name(text):
    match = re.search(r"(?:باسم|اسمه|اسمها|اسم|اسمو)\s+(.+?)(?:\s+(?:بتكلفة|تكلفة|بسعر|سعر|كمية|والكمية|وكمية)|$)", text or "", re.IGNORECASE)
    if match:
        return match.group(1).strip(" .،")
    cleaned = _strip_command_words(text)
    return cleaned if cleaned and not re.fullmatch(r"[-\d\s.,]+", cleaned) else ""


def _extract_item_fields(text):
    fields = {}
    name = _extract_ai_name(text)
    if name:
        fields["name"] = name
    patterns = {
        "cost": r"(?:تكلفة|التكلفة|بسعر تكلفة|سعر الشراء)\s*(-?\d+(?:[.,]\d+)?)",
        "selling_price": r"(?:سعر البيع|بيع|بسعر)\s*(-?\d+(?:[.,]\d+)?)",
        "quantity": r"(?:كمية|الكمية|عدد)\s*(-?\d+(?:[.,]\d+)?)",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            fields[field] = Decimal(match.group(1).replace(",", "."))
    return fields


def _extract_rate_or_amount_fields(text):
    fields = {}
    name = _extract_ai_name(text)
    if name:
        fields["name"] = name
    patterns = {
        "rate": r"(?:نسبة|معدل|ضريبة|rate|vat)\s*(-?\d+(?:[.,]\d+)?)",
        "amount": r"(?:مبلغ|بقيمة|amount)\s*(-?\d+(?:[.,]\d+)?)",
        "basic_salary": r"(?:راتب|الراتب|salary)\s*(-?\d+(?:[.,]\d+)?)",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            fields[field] = Decimal(match.group(1).replace(",", "."))
    return fields


def _extract_employee_reference(text):
    match = re.search(r"(?:للموظف|موظف|employee)\s+(.+?)(?:\s+(?:بمبلغ|مبلغ|بقيمة|amount)|$)", text or "", re.IGNORECASE)
    if match:
        return match.group(1).strip(" .،")
    return _extract_ai_name(text)


def _extract_ai_fields(entity, text):
    if entity == "item":
        return _extract_item_fields(text)
    if entity == "tax":
        return _extract_rate_or_amount_fields(text)
    if entity == "employee":
        fields = _extract_rate_or_amount_fields(text)
        name = _extract_ai_name(text)
        if name:
            fields["name"] = name
        return fields
    if entity == "advance":
        fields = _extract_rate_or_amount_fields(text)
        employee = _extract_employee_reference(text)
        if employee:
            fields["employee"] = employee
        return fields
    name = _extract_ai_name(text)
    return {"name": name} if name else {}


def _next_missing_field(entity, fields, intent):
    if intent in ("update", "delete") and not fields.get("target"):
        return "target"
    if intent == "update":
        if not fields.get("field"):
            return "field"
        if fields.get("value") in (None, ""):
            return "value"
        return ""
    if intent == "delete":
        return ""
    for field in AI_MANAGED_FIELDS.get(entity, []):
        if fields.get(field) in (None, ""):
            return field
    return ""


def _model_for_ai_entity(entity):
    return {
        "customer": Customer,
        "supplier": Supplier,
        "item": Item,
        "tax": Tax,
        "employee": Employee,
        "advance": EmployeeAdvance,
    }.get(entity)


def _ai_permission_codename(entity, intent):
    action = {
        "create": "add",
        "update": "change",
        "delete": "delete",
        "read": "view",
    }.get(intent, "view")
    model_name = {
        "customer": "customer",
        "supplier": "supplier",
        "item": "item",
        "tax": "tax",
        "employee": "employee",
        "advance": "employeeadvance",
    }.get(entity)
    app_label = "core" if entity in ("employee", "advance") else "invoicing"
    return f"{app_label}.{action}_{model_name}" if model_name else ""


def _user_can_ai_manage(user, entity, intent):
    if not user:
        return True
    permission = _ai_permission_codename(entity, intent)
    if not permission:
        return False
    codename = permission.split(".", 1)[1]
    try:
        from accounts.views import user_has_business_permission
        from core.models import Company
        company = None
        company_id = getattr(user, "_ai_company_id", None)
        if company_id:
            company = Company.objects.filter(id=company_id).select_related("active_plan").first()
        return user_has_business_permission(user, codename, company)
    except Exception:
        return bool(getattr(user, "is_superuser", False) or user.has_perm(permission))


def _find_entity_record(entity, branch_id, target):
    model = _model_for_ai_entity(entity)
    if not model or not target:
        return None
    qs = model.objects.all()
    if entity == "item":
        qs = qs.filter(branch_id=branch_id)
    if entity in ("employee", "advance"):
        qs = qs.filter(branch_id=branch_id) if entity == "employee" else qs.filter(branch_id=branch_id, employee__name__icontains=target)
    if entity == "advance":
        return qs.order_by("-date", "-id").first()
    return qs.filter(name__icontains=target).first()


def _create_ai_entity(entity, branch_id, fields):
    if entity == "customer":
        obj = Customer.objects.create(name=fields["name"])
        return f"تمت إضافة العميل: {obj.name}."
    if entity == "supplier":
        obj = Supplier.objects.create(name=fields["name"])
        return f"تمت إضافة المورد: {obj.name}."
    if entity == "item":
        obj = Item.objects.create(
            branch_id=branch_id,
            name=fields["name"],
            cost=fields["cost"],
            selling_price=fields["selling_price"],
            quantity=fields["quantity"],
        )
        return f"تمت إضافة الصنف: {obj.name}، الكمية {obj.quantity}، تكلفة {obj.cost}، وسعر البيع {obj.selling_price}."
    if entity == "tax":
        obj = Tax.objects.create(name=fields["name"], rate=fields["rate"])
        return f"تمت إضافة الضريبة: {obj.name} بنسبة {obj.rate}%."
    if entity == "employee":
        from core.models import Branch
        branch = Branch.objects.select_related("company").get(id=branch_id)
        obj = Employee.objects.create(
            company=branch.company,
            branch=branch,
            name=fields["name"],
            basic_salary=fields["basic_salary"],
            status="active",
        )
        return f"تمت إضافة الموظف: {obj.name} براتب أساسي {obj.basic_salary}."
    if entity == "advance":
        employee = Employee.objects.filter(branch_id=branch_id, name__icontains=fields["employee"], status="active").first()
        if not employee:
            return f"لم أجد موظفا باسم {fields['employee']} في الفرع الحالي."
        obj = EmployeeAdvance.objects.create(
            employee=employee,
            company=employee.company,
            branch=employee.branch,
            date=timezone.localdate(),
            amount=fields["amount"],
            paid_amount=Decimal("0"),
            status="open",
        )
        return f"تمت إضافة سلفة للموظف {employee.name} بمبلغ {obj.amount}."
    return ""


def _map_update_field(entity, field_text):
    normalized = _normalize_ai_text(field_text)
    if entity in ("customer", "supplier") or "اسم" in normalized:
        return "name"
    if any(word in normalized for word in ("تكلفة", "شراء", "cost")):
        return "cost"
    if any(word in normalized for word in ("سعر البيع", "بيع", "price")):
        return "selling_price"
    if any(word in normalized for word in ("كمية", "عدد", "quantity")):
        return "quantity"
    if any(word in normalized for word in ("نسبة", "ضريبة", "rate", "vat")):
        return "rate"
    if any(word in normalized for word in ("راتب", "salary")):
        return "basic_salary"
    if any(word in normalized for word in ("مبلغ", "amount")):
        return "amount"
    return ""


def _update_ai_entity(entity, branch_id, fields):
    obj = _find_entity_record(entity, branch_id, fields.get("target"))
    if not obj:
        return f"لم أجد {AI_MANAGED_ENTITY_LABELS.get(entity, 'السجل')} باسم {fields.get('target')}."
    field = _map_update_field(entity, fields.get("field"))
    if not field:
        return "لم أفهم الحقل المطلوب تعديله. قل مثلاً: الاسم، التكلفة، سعر البيع، أو الكمية."
    value = fields.get("value")
    if field in ("cost", "selling_price", "quantity", "rate", "basic_salary", "amount"):
        value = _extract_decimal(str(value))
        if value is None:
            return "القيمة الجديدة يجب أن تكون رقماً."
    setattr(obj, field, value)
    obj.save(update_fields=[field])
    return f"تم تعديل {AI_MANAGED_ENTITY_LABELS.get(entity, 'السجل')} {obj.name} بنجاح."


def _delete_ai_entity(entity, branch_id, fields):
    obj = _find_entity_record(entity, branch_id, fields.get("target"))
    if not obj:
        return f"لم أجد {AI_MANAGED_ENTITY_LABELS.get(entity, 'السجل')} باسم {fields.get('target')}."
    name = obj.name
    obj.delete()
    return f"تم حذف {AI_MANAGED_ENTITY_LABELS.get(entity, 'السجل')}: {name}."


def _read_ai_entity(entity, branch_id):
    model = _model_for_ai_entity(entity)
    if not model:
        return ""
    qs = model.objects.all()
    if entity == "item":
        qs = qs.filter(branch_id=branch_id)
    rows = list(qs.order_by("name")[:10])
    if not rows:
        return f"لا توجد بيانات مسجلة حالياً في {AI_MANAGED_ENTITY_LABELS.get(entity, 'هذا القسم')}."
    if entity == "item":
        details = [f"- {row.name}: الكمية {row.quantity}، التكلفة {row.cost}، سعر البيع {row.selling_price}" for row in rows]
    elif entity == "tax":
        details = [f"- {row.name}: {row.rate}%" for row in rows]
    elif entity == "employee":
        details = [f"- {row.name}: الراتب الأساسي {row.basic_salary}، الحالة {row.status}" for row in rows]
    elif entity == "advance":
        details = [f"- {row.employee.name}: مبلغ {row.amount}، المسدد {row.paid_amount}، المتبقي {row.remaining_amount}" for row in rows]
    else:
        details = [f"- {row.name}" for row in rows]
    return "هذه أول النتائج:\n" + "\n".join(details)


def handle_ai_management_command(branch_id, text, pending=None, user=None):
    pending = pending or {}
    if pending:
        intent = pending["intent"]
        entity = pending["entity"]
        fields = pending.get("fields", {})
        missing_field = pending.get("missing_field")
        if missing_field:
            fields[missing_field] = text.strip()
            if missing_field in ("cost", "selling_price", "quantity", "rate", "amount", "basic_salary"):
                number = _extract_decimal(text)
                fields[missing_field] = number if number is not None else ""
    else:
        intent = _detect_ai_intent(text)
        entity = _detect_ai_entity(text)
        fields = _extract_ai_fields(entity, text) if entity else {}

    if not intent or not entity:
        return None

    if not _user_can_ai_manage(user, entity, intent):
        return {
            "ok": True,
            "source": "ai_actions",
            "answer": f"لا أستطيع تنفيذ {AI_INTENT_LABELS.get(intent, intent)} {AI_MANAGED_ENTITY_LABELS.get(entity)} لأن حسابك لا يملك الصلاحية المطلوبة.",
            "pending": None,
        }

    if intent in ("update", "delete") and not fields.get("target"):
        fields["target"] = _extract_ai_name(text)
    if intent == "update" and not fields.get("field"):
        for word in ("الاسم", "اسم", "التكلفة", "تكلفة", "سعر البيع", "الكمية", "كمية"):
            if word in text:
                fields["field"] = word
                break
    if intent == "update" and fields.get("field") and not fields.get("value"):
        number = _extract_decimal(text)
        if number is not None:
            fields["value"] = str(number)

    missing_field = _next_missing_field(entity, fields, intent)
    if missing_field:
        return {
            "ok": True,
            "source": "ai_actions",
            "answer": f"تمام، فهمت أنك تريد {AI_INTENT_LABELS.get(intent, intent)} {AI_MANAGED_ENTITY_LABELS.get(entity)}. {AI_FIELD_QUESTIONS[missing_field]}",
            "pending": {
                "intent": intent,
                "entity": entity,
                "fields": {key: str(value) for key, value in fields.items()},
                "missing_field": missing_field,
            },
        }

    if intent == "create":
        answer = _create_ai_entity(entity, branch_id, fields)
    elif intent == "update":
        answer = _update_ai_entity(entity, branch_id, fields)
    elif intent == "delete":
        answer = _delete_ai_entity(entity, branch_id, fields)
    else:
        answer = _read_ai_entity(entity, branch_id)
    return {"ok": True, "source": "ai_actions", "answer": answer, "pending": None}


def command_from_camera_image(image_base64, media_type="image/jpeg", user_question=""):
    prompt = _professional_prompt(
        "visual_screen_or_camera_analysis",
        user_question or "اقرأ الصورة وحولها إلى أمر قصير قابل للتنفيذ داخل النظام المحاسبي.",
        {},
        (
            "حلل الصورة أو الشاشة بدقة. إذا كان المستخدم يسأل سؤالا عن البيانات المعروضة، أجب اعتمادا على ما يظهر في الصورة فقط واذكر أي نقص. "
            "إذا كانت الصورة فاتورة أو إيصال كاشير أو قائمة منتجات، استخرج أسماء المنتجات والكميات والأسعار الواضحة بصيغة قابلة للتنفيذ مثل: بيع 2 قلم بسعر 5 و1 دفتر بسعر 10. "
            "إذا كانت بطاقة أو ورقة لإضافة عميل أو مورد أو صنف، استخرج النوع والاسم والأرقام الواضحة فقط. "
            "إذا كان الطلب يتضمن إضافة أو حفظ، لا تقل إنه تم الحفظ؛ أعد مسودة أمر تنتظر موافقة المستخدم. "
            "إذا لم تتضح البيانات قل: لم أستطع قراءة بيانات كافية من الصورة."
        ),
    )
    result = _private_ai_request(
        prompt,
        max_new_tokens=220,
        task="camera_management_command",
        image_base64=image_base64,
        media_type=media_type,
    )
    if not result.get("ok"):
        return result
    text = (result.get("text") or "").strip()
    if not text or "لم أستطع" in text:
        return {
            "ok": False,
            "message": text or "لم أستطع قراءة بيانات كافية من الصورة. صوّر الاسم والأرقام بوضوح أو قل الطلب صوتيا.",
        }
    return {"ok": True, "command": text, "source": "camera"}


def _user_can_read_context(user, codename, branch_id=None):
    if not user:
        return True
    try:
        company = None
        if branch_id:
            from core.models import Branch
            from core.access import user_can_access_branch
            branch = Branch.objects.select_related("company").filter(id=branch_id).first()
            company = branch.company if branch else None
            if branch and not user_can_access_branch(user, branch):
                return False
        from accounts.views import user_has_business_permission
        return user_has_business_permission(user, codename, company=company)
    except Exception:
        return bool(getattr(user, "is_superuser", False) or user.has_perm(f"invoicing.{codename}") or user.has_perm(f"core.{codename}"))


def _restricted_context_message(context):
    labels = {
        "sales": "المبيعات والفواتير",
        "purchases": "المشتريات",
        "inventory": "المخزون والأصناف",
        "customers": "العملاء",
    }
    restricted = [labels[key] for key in context.get("restricted_sections", []) if key in labels]
    if not restricted:
        return ""
    return "تنبيه صلاحيات: لن أعرض أو أحلل بيانات " + "، ".join(restricted) + " لأن حسابك لا يملك صلاحية الاطلاع عليها."


def _question_requests_restricted_data(question, context):
    normalized = (question or "").lower()
    checks = {
        "sales": ("مبيعات", "فاتورة بيع", "فواتير البيع", "ايراد", "إيراد", "عملاء", "عميل"),
        "purchases": ("مشتريات", "فاتورة شراء", "فواتير الشراء", "مورد", "الموردين"),
        "inventory": ("مخزون", "صنف", "منتج", "كمية", "بضاعة"),
        "customers": ("عملاء", "عميل", "زبون"),
    }
    restricted = set(context.get("restricted_sections", []))
    return any(section in restricted and any(word in normalized for word in words) for section, words in checks.items())


def _safe_ratio(numerator, denominator):
    numerator = numerator or Decimal("0")
    denominator = denominator or Decimal("0")
    if not denominator:
        return None
    return (numerator / denominator * Decimal("100")).quantize(Decimal("0.01"))


def _money(value):
    return (value or Decimal("0")).quantize(Decimal("0.01"))


def _previous_month_window(today):
    current_start = today.replace(day=1)
    previous_end = current_start - timezone.timedelta(days=1)
    previous_start = previous_end.replace(day=1)
    return previous_start, previous_end


def branch_ai_context(branch_id, user=None):
    today = timezone.localdate()
    start = today.replace(day=1)
    previous_start, previous_end = _previous_month_window(today)
    invoices = Invoice.objects.filter(branch_id=branch_id)
    purchases = PurchaseInvoice.objects.filter(branch_id=branch_id)
    items = Item.objects.filter(branch_id=branch_id)
    month_invoices = invoices.filter(issue_date__date__range=[start, today])
    month_purchases = purchases.filter(issue_date__range=[start, today])
    previous_invoices = invoices.filter(issue_date__date__range=[previous_start, previous_end])
    previous_purchases = purchases.filter(issue_date__range=[previous_start, previous_end])
    can_view_sales = _user_can_read_context(user, "view_invoice", branch_id)
    can_view_purchases = _user_can_read_context(user, "view_purchaseinvoice", branch_id)
    can_view_inventory = _user_can_read_context(user, "view_item", branch_id)
    can_view_customers = _user_can_read_context(user, "view_customer", branch_id)
    restricted_sections = []
    if not can_view_sales:
        restricted_sections.append("sales")
    if not can_view_purchases:
        restricted_sections.append("purchases")
    if not can_view_inventory:
        restricted_sections.append("inventory")
    if not can_view_customers:
        restricted_sections.append("customers")
    sales_total = _money(month_invoices.aggregate(total=Coalesce(Sum("total_with_vat"), Decimal("0")))["total"]) if can_view_sales else None
    purchases_total = _money(month_purchases.aggregate(total=Coalesce(Sum("total_with_vat"), Decimal("0")))["total"]) if can_view_purchases else None
    previous_sales_total = _money(previous_invoices.aggregate(total=Coalesce(Sum("total_with_vat"), Decimal("0")))["total"]) if can_view_sales else None
    previous_purchases_total = _money(previous_purchases.aggregate(total=Coalesce(Sum("total_with_vat"), Decimal("0")))["total"]) if can_view_purchases else None
    active_items = items.filter(is_active=True)
    return {
        "period": f"{start} إلى {today}",
        "previous_period": f"{previous_start} إلى {previous_end}",
        "restricted_sections": restricted_sections,
        "sales_total": sales_total,
        "purchases_total": purchases_total,
        "previous_sales_total": previous_sales_total,
        "previous_purchases_total": previous_purchases_total,
        "sales_change_percent": _safe_ratio((sales_total or Decimal("0")) - (previous_sales_total or Decimal("0")), previous_sales_total) if can_view_sales else None,
        "purchases_change_percent": _safe_ratio((purchases_total or Decimal("0")) - (previous_purchases_total or Decimal("0")), previous_purchases_total) if can_view_purchases else None,
        "gross_margin_percent": _safe_ratio((sales_total or Decimal("0")) - (purchases_total or Decimal("0")), sales_total) if can_view_sales and can_view_purchases else None,
        "invoice_count": month_invoices.count() if can_view_sales else None,
        "purchase_count": month_purchases.count() if can_view_purchases else None,
        "average_invoice_value": _money(sales_total / month_invoices.count()) if can_view_sales and month_invoices.count() else None,
        "average_purchase_value": _money(purchases_total / month_purchases.count()) if can_view_purchases and month_purchases.count() else None,
        "unposted_sales_count": month_invoices.filter(journal_entry__isnull=True).count() if can_view_sales else None,
        "unposted_purchases_count": month_purchases.filter(journal_entry__isnull=True).count() if can_view_purchases else None,
        "inventory_value": active_items.aggregate(total=Coalesce(Sum(F("quantity") * F("cost")), Decimal("0")))["total"] if can_view_inventory else None,
        "inventory_items_count": active_items.count() if can_view_inventory else None,
        "zero_stock_count": active_items.filter(quantity__lte=0).count() if can_view_inventory else None,
        "low_stock_count": active_items.filter(quantity__lte=F("min_quantity")).count() if can_view_inventory else None,
        "low_stock_items": list(active_items.filter(quantity__lte=F("min_quantity")).values_list("name", flat=True)[:8]) if can_view_inventory else [],
        "top_items": list(
            InvoiceItem.objects.filter(invoice__branch_id=branch_id)
            .values("item__name")
            .annotate(quantity=Coalesce(Sum("quantity"), Decimal("0")), total=Coalesce(Sum("line_total_with_vat"), Decimal("0")))
            .order_by("-total")[:6]
        ) if can_view_sales and can_view_inventory else [],
        "top_customers": list(
            month_invoices.values("customer__name")
            .annotate(total=Coalesce(Sum("total_with_vat"), Decimal("0")), invoices=Count("id"))
            .order_by("-total")[:5]
        ) if can_view_sales and can_view_customers else [],
        "top_suppliers": list(
            month_purchases.values("supplier__name")
            .annotate(total=Coalesce(Sum("total_with_vat"), Decimal("0")), purchases=Count("id"))
            .order_by("-total")[:5]
        ) if can_view_purchases else [],
        "customers_count": invoices.values("customer_id").distinct().count() if can_view_sales and can_view_customers else None,
    }


def local_financial_insights(context):
    tips = []
    sales = context["sales_total"] or Decimal("0")
    purchases = context["purchases_total"] or Decimal("0")
    gross_margin = context.get("gross_margin_percent")
    sales_change = context.get("sales_change_percent")
    purchases_change = context.get("purchases_change_percent")
    if sales <= 0:
        tips.append("لا توجد مبيعات مسجلة في الفترة الحالية. ابدأ بمراجعة إدخال الفواتير أو نشاط الفرع.")
    if purchases > sales and sales > 0:
        tips.append("المشتريات أعلى من المبيعات في الفترة الحالية؛ راجع المخزون البطيء وسياسة الشراء.")
    if gross_margin is not None:
        if gross_margin < 15:
            tips.append(f"هامش الربح التقريبي منخفض ({gross_margin}%). افحص الخصومات وتكلفة الأصناف وتسعير المنتجات الأعلى مبيعًا.")
        elif gross_margin > 45:
            tips.append(f"هامش الربح التقريبي قوي ({gross_margin}%). حافظ على توفر الأصناف الأعلى ربحية ولا تتركها تنفد.")
    if sales_change is not None:
        if sales_change <= -20:
            tips.append(f"المبيعات منخفضة بنسبة {abs(sales_change)}% مقارنة بالشهر السابق. راجع العملاء الأعلى شراء وتواصل مع العملاء المتوقفين.")
        elif sales_change >= 20:
            tips.append(f"المبيعات مرتفعة بنسبة {sales_change}% مقارنة بالشهر السابق. تأكد أن المخزون والشراء يواكبان الطلب بدون زيادة مبالغ فيها.")
    if purchases_change is not None and purchases_change >= 35 and (sales_change is None or purchases_change > sales_change + 15):
        tips.append(f"المشتريات ارتفعت {purchases_change}% مقارنة بالشهر السابق. تحقق أن الزيادة مرتبطة بطلب فعلي وليست تراكم مخزون.")
    if context["low_stock_count"]:
        tips.append(f"يوجد {context['low_stock_count']} صنف عند حد التنبيه أو أقل، وأهمها: {', '.join(context['low_stock_items'])}.")
    if context.get("zero_stock_count"):
        tips.append(f"يوجد {context['zero_stock_count']} صنف رصيده صفر أو أقل. راجعها لأنها قد تسبب فقد مبيعات أو أخطاء في الفواتير.")
    if context.get("unposted_sales_count") or context.get("unposted_purchases_count"):
        tips.append(f"توجد عمليات غير مرحلة: مبيعات {context.get('unposted_sales_count') or 0} ومشتريات {context.get('unposted_purchases_count') or 0}. رحلها قبل الاعتماد على التقارير الشهرية.")
    if context.get("top_items"):
        top = context["top_items"][0]
        tips.append(f"أعلى صنف مبيعًا هذا الشهر هو {top.get('item__name')} بإجمالي {top.get('total')}. راقب رصيده وهامشه لأنه مؤثر في النتيجة.")
    if context["invoice_count"] and not context["customers_count"]:
        tips.append("توجد فواتير بدون تنوع واضح في العملاء؛ راجع بيانات العملاء وربطها بالفواتير.")
    if not tips:
        tips.append("المؤشرات الأساسية مستقرة حاليا. تابع التدفق النقدي والمخزون بشكل أسبوعي.")
    return tips


def strong_local_financial_answer(context, question="", restricted_message=""):
    tips = local_financial_insights(context)[:4]
    lines = []
    if restricted_message:
        lines.append(restricted_message)
    lines.extend([
        "تحليل احترافي مبني على بيانات النظام:",
        f"قرأت البيانات المتاحة للفرع خلال الفترة {context.get('period')} وربطت المبيعات والمشتريات والمخزون والعمليات غير المرحلة حسب صلاحيات المستخدم.",
        "",
        "الملخص التنفيذي:",
        f"- المبيعات: {_format_money(context.get('sales_total')) if context.get('sales_total') is not None else 'غير متاحة حسب الصلاحيات'}",
        f"- المشتريات: {_format_money(context.get('purchases_total')) if context.get('purchases_total') is not None else 'غير متاحة حسب الصلاحيات'}",
        f"- هامش الربح التقريبي: {context.get('gross_margin_percent') if context.get('gross_margin_percent') is not None else 'غير متاح'}%",
        f"- قيمة المخزون: {_format_money(context.get('inventory_value')) if context.get('inventory_value') is not None else 'غير متاحة حسب الصلاحيات'}",
        f"- العمليات غير المرحلة: مبيعات {context.get('unposted_sales_count') or 0}، مشتريات {context.get('unposted_purchases_count') or 0}",
    ])
    if context.get("top_items"):
        top = context["top_items"][0]
        lines.append(f"- أعلى صنف مبيعا: {top.get('item__name')} بإجمالي {top.get('total')}.")
    lines.extend(["", "التشخيص:"])
    if context.get("gross_margin_percent") is not None and context["gross_margin_percent"] < 15:
        lines.append("- الربحية تحتاج مراجعة؛ ابدأ بالخصومات وتكلفة الأصناف الأعلى مبيعا.")
    elif context.get("sales_total") and context.get("sales_total") > 0:
        lines.append("- يوجد نشاط بيع مسجل؛ الأهم الآن متابعة المخزون والتحصيل والعمليات غير المرحلة.")
    else:
        lines.append("- لا توجد مبيعات كافية في الفترة الحالية، لذلك الأولوية لإدخال الفواتير أو مراجعة نشاط الفرع.")
    if context.get("sales_change_percent") is not None:
        lines.append(f"- تغير المبيعات عن الفترة السابقة: {context.get('sales_change_percent')}%.")
    if context.get("purchases_change_percent") is not None:
        lines.append(f"- تغير المشتريات عن الفترة السابقة: {context.get('purchases_change_percent')}%.")
    lines.extend([
        "",
        "قرار عملي مقترح:",
        "- لا توسع الشراء قبل التأكد من دوران الأصناف الأعلى ربحا ومطابقة المخزون الفعلي مع النظام.",
        "- رحّل أي عمليات غير مرحلة قبل الاعتماد على التقرير لاتخاذ قرار مالي.",
        "- إذا كانت المبيعات منخفضة، ابدأ بحملة قصيرة على أعلى الأصناف هامشا بدلا من تخفيض شامل للأسعار.",
    ])
    if tips:
        lines.extend(["", "تنبيهات من بياناتك الحالية:"])
        lines.extend(f"- {tip}" for tip in tips)
    lines.extend([
        "",
        "ما أحتاجه منك لتحليل أدق:",
        "- حدد الشركة والفرع والفترة أو اسم المنتج/العميل.",
        "- مثال: حلل مبيعات هذا الشهر، أو ما المنتجات ضعيفة الربح؟ أو توقع أثر إضافة 500 حبة من منتج محدد.",
    ])
    return "\n".join(lines)


def _format_money(value):
    return f"{_money(value)}"


def _extract_decimal_from_question(question, default=None):
    match = re.search(r"(\d+(?:[.,]\d+)?)", question or "")
    if not match:
        return default
    try:
        return Decimal(match.group(1).replace(",", "."))
    except Exception:
        return default


def _find_item_mentioned(branch_id, question):
    normalized = (question or "").lower()
    candidates = Item.objects.filter(branch_id=branch_id, is_active=True).order_by("-id")
    exact = [item for item in candidates if item.name and item.name.lower() in normalized]
    if exact:
        return exact[0]
    words = [word for word in re.split(r"\s+", normalized) if len(word) >= 3]
    scored = []
    for item in candidates:
        item_words = [word for word in re.split(r"\s+", item.name.lower()) if len(word) >= 3]
        score = len(set(words) & set(item_words))
        if score:
            scored.append((score, item))
    return sorted(scored, key=lambda row: row[0], reverse=True)[0][1] if scored else None


def _item_sales_stats(branch_id, item_id, days=90):
    today = timezone.localdate()
    start = today - timezone.timedelta(days=days)
    rows = InvoiceItem.objects.filter(
        invoice__branch_id=branch_id,
        item_id=item_id,
        invoice__issue_date__date__range=[start, today],
    )
    return {
        "start": start,
        "end": today,
        "quantity": rows.aggregate(total=Coalesce(Sum("quantity"), Decimal("0")))["total"],
        "revenue": rows.aggregate(total=Coalesce(Sum("line_total"), Decimal("0")))["total"],
        "invoice_count": rows.values("invoice_id").distinct().count(),
    }


def _build_product_performance_rows(branch_id, start, end):
    if not Item.objects.filter(branch_id=branch_id, is_active=True).exists():
        return []
    sold = {
        row["item_id"]: row
        for row in InvoiceItem.objects.filter(
            invoice__branch_id=branch_id,
            invoice__issue_date__date__range=[start, end],
            item_id__isnull=False,
        ).values("item_id").annotate(
            sold_qty=Coalesce(Sum("quantity"), Decimal("0")),
            revenue=Coalesce(Sum("line_total"), Decimal("0")),
        )
    }
    rows = []
    for item in Item.objects.filter(branch_id=branch_id, is_active=True):
        sold_row = sold.get(item.id, {})
        unit_profit = _money((item.selling_price or Decimal("0")) - (item.cost or Decimal("0")))
        margin_percent = _safe_ratio(unit_profit, item.selling_price)
        sold_qty = sold_row.get("sold_qty") or Decimal("0")
        revenue = sold_row.get("revenue") or Decimal("0")
        estimated_profit = _money(unit_profit * sold_qty)
        rows.append({
            "item": item,
            "sold_qty": sold_qty,
            "revenue": revenue,
            "unit_profit": unit_profit,
            "margin_percent": margin_percent,
            "estimated_profit": estimated_profit,
            "stock": item.quantity,
        })
    return rows


def product_performance_advice(branch_id, question, user=None):
    normalized = (question or "").lower()
    triggers = (
        "ربح المنتج", "ربحية", "الأرباح", "ارباح", "أداء المنتجات", "اداء المنتجات",
        "منتجات ضعيفة", "ربح منخفض", "الربح المنخفض", "أضفت", "اضفت", "إضافة 500", "500 حبة",
        "توقع", "متوقع", "سيناريو", "زودت المخزون", "زيادة المخزون",
        "اقترح منتجات", "اقتراح منتجات", "أفكار منتجات", "افكار منتجات", "أفكار مناسبة", "افكار مناسبة",
    )
    if not any(trigger in normalized for trigger in triggers):
        return ""
    if not _user_can_read_context(user, "view_item", branch_id):
        return "لا أستطيع تحليل المنتجات والمخزون لأن حسابك لا يملك صلاحية عرض الأصناف."
    if not _user_can_read_context(user, "view_invoice", branch_id):
        return "لا أستطيع تقدير ربحية المنتجات بدقة لأن حسابك لا يملك صلاحية عرض فواتير البيع."

    branch = Branch.objects.select_related("company").filter(id=branch_id).first()
    start, end = _date_range_from_question(question)
    rows = _build_product_performance_rows(branch_id, start, end)
    if not rows:
        return "لا توجد منتجات نشطة كافية لتحليل الأداء في الفرع الحالي."

    item = _find_item_mentioned(branch_id, question)
    requested_qty = _extract_decimal_from_question(question)
    lines = [
        f"تقرير أداء المنتجات للفترة {start} إلى {end}:",
        f"- الشركة: {branch.company.name if branch and branch.company_id else 'غير محددة'}",
        f"- الفرع: {branch.name if branch else branch_id}",
    ]

    if item and requested_qty:
        stats = _item_sales_stats(branch_id, item.id)
        unit_profit = _money((item.selling_price or Decimal("0")) - (item.cost or Decimal("0")))
        gross_profit_if_sold = _money(unit_profit * requested_qty)
        expected_daily_sales = (stats["quantity"] / Decimal("90")) if stats["quantity"] else Decimal("0")
        expected_sell_days = (requested_qty / expected_daily_sales).quantize(Decimal("0.1")) if expected_daily_sales else None
        current_stock_profit = _money(unit_profit * (item.quantity or Decimal("0")))
        after_stock_profit_capacity = _money(unit_profit * ((item.quantity or Decimal("0")) + requested_qty))
        margin_percent = _safe_ratio(unit_profit, item.selling_price)
        lines.extend([
            f"سيناريو إضافة {requested_qty} حبة من {item.name}:",
            f"- تكلفة الوحدة الحالية: {_format_money(item.cost)}",
            f"- سعر البيع الحالي: {_format_money(item.selling_price)}",
            f"- ربح الوحدة التقريبي قبل المصاريف العامة: {_format_money(unit_profit)}",
            f"- هامش الوحدة التقريبي: {margin_percent if margin_percent is not None else 'غير متاح'}%",
            f"- إذا تم بيع كامل الكمية المضافة بنفس السعر والتكلفة فمتوقع زيادة مجمل الربح بنحو {_format_money(gross_profit_if_sold)}.",
            f"- الطاقة الربحية للمخزون الحالي تقريبا: {_format_money(current_stock_profit)}، وبعد الإضافة تصبح {_format_money(after_stock_profit_capacity)} إذا بيع كامل المخزون.",
        ])
        if expected_sell_days:
            lines.append(f"- بناء على بيع آخر 90 يوما ({stats['quantity']} حبة)، قد تحتاج الكمية المضافة حوالي {expected_sell_days} يوم للبيع إذا بقي الطلب بنفس المستوى.")
        else:
            lines.append("- لا توجد مبيعات تاريخية كافية لهذا المنتج؛ اعتبر التوقع ربحا محتملا وليس توقع طلب مؤكد.")
        if unit_profit <= 0:
            lines.append("- تحذير: ربح الوحدة صفر أو سلبي. لا أنصح بزيادة الكمية قبل تعديل السعر أو التكلفة.")
        elif margin_percent is not None and margin_percent < 15:
            lines.append("- الهامش منخفض؛ زد الكمية فقط إذا كان المنتج يجذب عملاء أو يرفع مبيعات منتجات أخرى ذات هامش أعلى.")

    top_profit = sorted(rows, key=lambda row: row["estimated_profit"], reverse=True)[:5]
    low_margin = sorted(
        [row for row in rows if row["margin_percent"] is not None],
        key=lambda row: (row["margin_percent"], -row["sold_qty"]),
    )[:5]
    slow_or_dead = sorted(
        [row for row in rows if row["sold_qty"] <= 0 and row["stock"] > 0],
        key=lambda row: row["stock"] * row["item"].cost,
        reverse=True,
    )[:5]

    lines.append("أفضل منتجات حسب الربح التقديري:")
    lines.extend(
        f"- {row['item'].name}: مبيعات {row['sold_qty']}، ربح وحدة {_format_money(row['unit_profit'])}، ربح تقديري {_format_money(row['estimated_profit'])}"
        for row in top_profit
    )
    lines.append("منتجات تحتاج مراجعة لأنها منخفضة الهامش أو تؤثر على الربحية:")
    lines.extend(
        f"- {row['item'].name}: هامش {row['margin_percent']}%، ربح وحدة {_format_money(row['unit_profit'])}، مبيعات {row['sold_qty']}"
        for row in low_margin
    )
    if slow_or_dead:
        lines.append("مخزون راكد أو بلا مبيعات في الفترة:")
        lines.extend(
            f"- {row['item'].name}: مخزون {row['stock']}، قيمة تقريبية {_format_money(row['stock'] * row['item'].cost)}"
            for row in slow_or_dead
        )
    lines.extend([
        "توصية عملية:",
        "- زد شراء المنتجات عالية الربح وعالية الدوران أولا.",
        "- قلل أو أوقف المنتجات منخفضة الربح إلا إذا كانت تجذب العملاء أو تكمل سلة البيع.",
        "- قبل شراء كمية كبيرة، اختبر كمية أصغر أو عرضا محدودا، ثم قارن سرعة البيع والهامش خلال أسبوعين.",
        "- للأفكار والمنتجات الجديدة، اسألني: اقترح منتجات مناسبة لنشاطي في السوق السعودي، وسأجمع بين بيانات نظامك ومصادر عامة موثوقة عند توفر الإنترنت.",
    ])
    if any(term in normalized for term in ("اقترح", "اقتراح", "أفكار", "افكار", "منتجات جديدة")):
        market_answer = free_web_general_answer("أفكار منتجات وتجارة مناسبة للسوق السعودي والمشاريع الصغيرة")
        if market_answer:
            lines.extend(["معلومات سوقية عامة من مصادر مفتوحة:", market_answer])
    return "\n".join(lines)


def _date_range_from_question(question):
    today = timezone.localdate()
    normalized = (question or "").lower()
    if any(word in normalized for word in ("اليوم", "today")):
        return today, today
    if any(word in normalized for word in ("أمس", "امس", "yesterday")):
        day = today - timezone.timedelta(days=1)
        return day, day
    if any(word in normalized for word in ("الشهر السابق", "الشهر الماضي", "last month")):
        return _previous_month_window(today)
    if any(word in normalized for word in ("السنة", "هذا العام", "year")):
        return today.replace(month=1, day=1), today
    return today.replace(day=1), today


def _invoice_number_from_question(question):
    matches = re.findall(r"(?:فاتورة|invoice|رقم)\s*([A-Za-z0-9\-_/]+)", question or "", re.IGNORECASE)
    ignored = {"بيع", "شراء", "sales", "purchase", "invoice"}
    for match in matches:
        if match.lower() not in ignored:
            return match
    loose = re.search(r"\b([A-Z]+-\d+[A-Za-z0-9\-_/]*)\b", question or "", re.IGNORECASE)
    return loose.group(1) if loose else ""


def _answer_invoice_details(branch_id, question, user):
    normalized = (question or "").lower()
    invoice_number = _invoice_number_from_question(question)
    if any(word in normalized for word in ("فاتورة بيع", "sales invoice", "مبيعات")):
        if not _user_can_read_context(user, "view_invoice", branch_id):
            return "لا أستطيع عرض تفاصيل فواتير البيع لأن حسابك لا يملك الصلاحية المطلوبة."
        qs = Invoice.objects.filter(branch_id=branch_id).select_related("customer")
        if invoice_number:
            qs = qs.filter(invoice_number__icontains=invoice_number)
        invoice = qs.order_by("-issue_date").first()
        if not invoice:
            return "لم أجد فاتورة بيع مطابقة في الفرع الحالي."
        lines = InvoiceItem.objects.filter(invoice=invoice).select_related("item")
        details = [
            f"فاتورة البيع {invoice.invoice_number}",
            f"العميل: {invoice.customer.name}",
            f"التاريخ: {invoice.issue_date:%Y-%m-%d %H:%M}",
            f"قبل الضريبة: {_format_money(invoice.total_amount)}",
            f"الضريبة: {_format_money(invoice.total_vat)}",
            f"الإجمالي شامل الضريبة: {_format_money(invoice.total_with_vat)}",
            f"طريقة الدفع: {invoice.payment_method}",
            f"مرتبطة بقيد: {'نعم' if invoice.journal_entry_id else 'لا'}",
            "البنود:",
        ]
        details.extend(f"- {line.description}: كمية {line.quantity}، سعر {line.unit_price}، إجمالي {line.line_total_with_vat}" for line in lines)
        return "\n".join(details)
    if any(word in normalized for word in ("فاتورة شراء", "purchase invoice", "مشتريات")) and invoice_number:
        if not _user_can_read_context(user, "view_purchaseinvoice", branch_id):
            return "لا أستطيع عرض تفاصيل فواتير الشراء لأن حسابك لا يملك الصلاحية المطلوبة."
        invoice = PurchaseInvoice.objects.filter(branch_id=branch_id, invoice_number__icontains=invoice_number).select_related("supplier").order_by("-issue_date").first()
        if not invoice:
            return "لم أجد فاتورة شراء مطابقة في الفرع الحالي."
        lines = PurchaseItem.objects.filter(invoice=invoice).select_related("item")
        details = [
            f"فاتورة الشراء {invoice.invoice_number}",
            f"المورد: {invoice.supplier.name}",
            f"التاريخ: {invoice.issue_date:%Y-%m-%d}",
            f"قبل الضريبة: {_format_money(invoice.total_before_vat)}",
            f"الضريبة: {_format_money(invoice.vat_amount)}",
            f"الإجمالي شامل الضريبة: {_format_money(invoice.total_with_vat)}",
            f"مرتبطة بقيد: {'نعم' if invoice.journal_entry_id else 'لا'}",
            "البنود:",
        ]
        details.extend(f"- {line.item.name}: كمية {line.quantity}، سعر {line.price}" for line in lines)
        return "\n".join(details)
    return ""


def _answer_account_scope_question(branch_id, question, user=None):
    normalized = (question or "").strip().lower()
    asks_company_scope = any(term in normalized for term in (
        "كم عدد الشركات", "عدد الشركات", "شركاتي", "الشركات في حسابي", "شركات في حسابي",
        "الشركات عندي", "الشركات لدي", "my companies", "company count",
    ))
    asks_branch_scope = any(term in normalized for term in (
        "كم عدد الفروع", "عدد الفروع", "فروعي", "الفروع في حسابي", "فروع في حسابي",
        "branches count", "my branches",
    ))
    if not asks_company_scope and not asks_branch_scope:
        return ""
    if not getattr(user, "is_authenticated", False):
        return "لا أستطيع معرفة الشركات أو الفروع قبل تسجيل الدخول."

    companies = user_companies(user).order_by("name")
    branches = Branch.objects.filter(company__in=companies, is_active=True).select_related("company").order_by("company__name", "name")
    current_branch = Branch.objects.filter(id=branch_id).select_related("company").first() if branch_id else None

    lines = ["هذه المعلومة من بيانات النظام:"]
    if asks_company_scope:
        lines.append(f"- عدد الشركات المتاحة في حسابك: {companies.count()}.")
        company_names = list(companies.values_list("name", flat=True)[:5])
        if company_names:
            lines.append("- أمثلة: " + "، ".join(company_names) + ("..." if companies.count() > 5 else "."))
    if asks_branch_scope:
        lines.append(f"- عدد الفروع المتاحة في حسابك: {branches.count()}.")
    if current_branch:
        lines.append(f"- الفرع المحدد الآن: {current_branch.company.name} / {current_branch.name}.")
    lines.append("يمكنك تغيير الشركة أو الفرع من صفحة اختيار الشركة والفرع.")
    return "\n".join(lines)


def _answer_precise_accounting_question(branch_id, question, user=None):
    normalized = (question or "").lower()
    start, end = _date_range_from_question(question)

    account_scope = _answer_account_scope_question(branch_id, question, user=user)
    if account_scope:
        return account_scope

    invoice_details = _answer_invoice_details(branch_id, question, user)
    if invoice_details:
        return invoice_details

    product_advice = product_performance_advice(branch_id, question, user=user)
    if product_advice:
        return product_advice

    if any(word in normalized for word in ("تقرير", "ملخص", "الوضع المالي", "الأرقام", "تحليل", "dashboard", "report")):
        context = branch_ai_context(branch_id, user=user)
        return strong_local_financial_answer(context, question)

    if any(word in normalized for word in ("منتج", "صنف", "مخزون", "كمية", "stock", "product")):
        if not _user_can_read_context(user, "view_item", branch_id):
            return "لا أستطيع عرض بيانات المنتجات أو المخزون لأن حسابك لا يملك الصلاحية المطلوبة."
        items = Item.objects.filter(branch_id=branch_id, is_active=True)
        low = items.filter(quantity__lte=F("min_quantity")).order_by("quantity")[:8]
        top = InvoiceItem.objects.filter(invoice__branch_id=branch_id, invoice__issue_date__date__range=[start, end]).values("item__name").annotate(quantity=Coalesce(Sum("quantity"), Decimal("0")), total=Coalesce(Sum("line_total_with_vat"), Decimal("0"))).order_by("-total")[:8]
        inventory_value = items.aggregate(total=Coalesce(Sum(F("quantity") * F("cost")), Decimal("0")))["total"]
        lines = [
            f"تقرير المنتجات والمخزون للفترة {start} إلى {end}:",
            f"- عدد الأصناف النشطة: {items.count()}",
            f"- قيمة المخزون بالتكلفة: {_format_money(inventory_value)}",
            f"- أصناف عند حد التنبيه أو أقل: {items.filter(quantity__lte=F('min_quantity')).count()}",
        ]
        if low:
            lines.append("الأصناف التي تحتاج متابعة:")
            lines.extend(f"- {item.name}: الكمية {item.quantity}، حد التنبيه {item.min_quantity}" for item in low)
        if top:
            lines.append("الأصناف الأعلى مبيعًا:")
            lines.extend(f"- {row['item__name']}: كمية {row['quantity']}، إجمالي {row['total']}" for row in top)
        lines.append("نصيحة تجارية: اربط إعادة الطلب بالأصناف الأعلى دورانًا، ولا ترفع مخزون الأصناف الراكدة إلا بعد مراجعة الطلب الفعلي.")
        return "\n".join(lines)

    if any(word in normalized for word in ("فاتورة", "فواتير", "مبيعات", "مشتريات", "sales", "purchase")):
        sales_allowed = _user_can_read_context(user, "view_invoice", branch_id)
        purchases_allowed = _user_can_read_context(user, "view_purchaseinvoice", branch_id)
        lines = [f"ملخص الفواتير للفترة {start} إلى {end}:"]
        if sales_allowed:
            sales = Invoice.objects.filter(branch_id=branch_id, issue_date__date__range=[start, end])
            lines.extend([
                f"- عدد فواتير البيع: {sales.count()}",
                f"- إجمالي البيع شامل الضريبة: {_format_money(sales.aggregate(total=Coalesce(Sum('total_with_vat'), Decimal('0')))['total'])}",
                f"- فواتير بيع غير مرحلة: {sales.filter(journal_entry__isnull=True).count()}",
            ])
        else:
            lines.append("- فواتير البيع غير متاحة حسب صلاحياتك.")
        if purchases_allowed:
            purchases = PurchaseInvoice.objects.filter(branch_id=branch_id, issue_date__range=[start, end])
            lines.extend([
                f"- عدد فواتير الشراء: {purchases.count()}",
                f"- إجمالي الشراء شامل الضريبة: {_format_money(purchases.aggregate(total=Coalesce(Sum('total_with_vat'), Decimal('0')))['total'])}",
                f"- فواتير شراء غير مرحلة: {purchases.filter(journal_entry__isnull=True).count()}",
            ])
        else:
            lines.append("- فواتير الشراء غير متاحة حسب صلاحياتك.")
        lines.append("نصيحة تشغيلية: ابدأ بترحيل الفواتير غير المرحلة قبل اتخاذ قرار شراء أو تحليل ربحية.")
        return "\n".join(lines)

    if any(word in normalized for word in ("راتب", "رواتب", "سلفة", "موظف", "payroll", "salary", "advance")):
        if not _user_can_read_context(user, "view_salaryrecord", branch_id) and not _user_can_read_context(user, "view_employeeadvance", branch_id):
            return "لا أستطيع عرض بيانات الرواتب أو السلف لأن حسابك لا يملك الصلاحية المطلوبة."
        employees = Employee.objects.filter(branch_id=branch_id)
        advances = EmployeeAdvance.objects.filter(branch_id=branch_id)
        salaries = SalaryRecord.objects.filter(branch_id=branch_id)
        open_advances = advances.filter(status="open").aggregate(total=Coalesce(Sum(F("amount") - F("paid_amount")), Decimal("0")))["total"]
        pending_salaries = salaries.filter(status__in=["draft", "approved"]).aggregate(total=Coalesce(Sum("net_salary"), Decimal("0")))["total"]
        return "\n".join([
            "ملخص الموظفين والرواتب والسلف:",
            f"- عدد الموظفين: {employees.count()}",
            f"- صافي رواتب غير مدفوعة/قيد المتابعة: {_format_money(pending_salaries)}",
            f"- رصيد السلف المفتوحة: {_format_money(open_advances)}",
            f"- عدد السلف المفتوحة: {advances.filter(status='open').count()}",
            "نصيحة إدارية: راجع السلف المفتوحة قبل اعتماد الرواتب، وضع حدًا داخليًا للسلفة كنسبة من الراتب لتقليل ضغط السيولة.",
        ])

    if any(word in normalized for word in ("قيد", "قيود", "journal", "ترحيل")):
        if not _user_can_read_context(user, "view_journalentry", branch_id):
            return "لا أستطيع عرض القيود لأن حسابك لا يملك الصلاحية المطلوبة."
        entries = JournalEntry.objects.filter(branch_id=branch_id, date__range=[start, end])
        debit = JournalEntryLine.objects.filter(entry__branch_id=branch_id, entry__date__range=[start, end]).aggregate(total=Coalesce(Sum("debit"), Decimal("0")))["total"]
        credit = JournalEntryLine.objects.filter(entry__branch_id=branch_id, entry__date__range=[start, end]).aggregate(total=Coalesce(Sum("credit"), Decimal("0")))["total"]
        return "\n".join([
            f"ملخص القيود للفترة {start} إلى {end}:",
            f"- عدد القيود: {entries.count()}",
            f"- إجمالي المدين: {_format_money(debit)}",
            f"- إجمالي الدائن: {_format_money(credit)}",
            f"- الفرق: {_format_money(debit - credit)}",
            "نصيحة رقابية: إذا ظهر فرق بين المدين والدائن فراجع القيود اليدوية والعمليات غير المرحلة فورًا.",
        ])

    return ""


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
    (("القيد المحاسبي", "قيد محاسبي", "القيد المزدوج", "double entry"), "القيد المحاسبي هو تسجيل أثر العملية المالية في الحسابات. غالبا يتكون من طرف مدين وطرف دائن، ويجب أن يتساوى مجموع المدين مع مجموع الدائن. مثال بسيط: عند بيع نقدي يكون الصندوق مدينا والإيراد دائنا، ومع الضريبة تسجل ضريبة المخرجات دائنة حسب النظام."),
    (("ميزان المراجعة",), "ميزان المراجعة يجمع أرصدة الحسابات للتأكد من توازن المدين والدائن، لكنه لا يضمن عدم وجود أخطاء تصنيف أو ترحيل."),
    (("قائمة الدخل", "الربح والخسارة"), "قائمة الدخل تعرض الإيرادات والمصروفات خلال فترة معينة للوصول إلى صافي الربح أو الخسارة."),
    (("المركز المالي", "الميزانية"), "قائمة المركز المالي تعرض الأصول والخصوم وحقوق الملكية. معادلتها: الأصول = الخصوم + حقوق الملكية."),
    (("التدفق النقدي", "السيولة"), "التدفق النقدي يوضح حركة دخول وخروج النقد، وهو مهم لأن الربح لا يعني دائما توفر السيولة."),
    (("ضريبة القيمة المضافة", "vat"), "ضريبة القيمة المضافة تظهر في المبيعات كضريبة مخرجات وفي المشتريات كضريبة مدخلات، وصافي المستحق هو الفرق بينهما غالبا."),
]

LOCAL_PROFESSIONAL_KNOWLEDGE = [
    (("دورة محاسبية", "الدورة المحاسبية"), "الدورة المحاسبية تبدأ بتحليل المستند، ثم إنشاء القيد، ثم الترحيل للأستاذ، ثم ميزان المراجعة، ثم التسويات، ثم القوائم المالية، ثم الإقفال. داخل النظام راقب دائما أن كل فاتورة أو راتب أو سلفة لها قيد مرتبط."),
    (("استحقاق", "أساس الاستحقاق"), "أساس الاستحقاق يعني تسجيل الإيراد عند تحققه والمصروف عند حدوثه، حتى لو لم يتم التحصيل أو الدفع نقدا. لذلك اعتماد الراتب يثبت مصروف ورواتب مستحقة، أما الدفع فيخفض النقدية."),
    (("نقدي", "أساس نقدي"), "الأساس النقدي يسجل العملية عند قبض أو دفع النقد فقط. في الأنظمة المحاسبية للشركات غالبا يكون أساس الاستحقاق أدق لأنه يوضح الالتزامات والمستحقات."),
    (("ذمم مدينة", "العملاء"), "الذمم المدينة هي مبالغ مستحقة على العملاء. تزيد عند البيع الآجل وتقل عند التحصيل. راقب أعمار الديون حتى لا تتحول المبيعات إلى سيولة متأخرة."),
    (("ذمم دائنة", "الموردين"), "الذمم الدائنة هي مبالغ مستحقة للموردين. تزيد عند الشراء الآجل وتقل عند السداد. مراجعتها تساعد على إدارة السيولة وتجنب التأخر في الدفع."),
    (("المخزون", "تكلفة المخزون"), "المخزون أصل متداول. عند الشراء يزيد المخزون، وعند البيع تنخفض الكمية وتظهر تكلفة البضاعة المباعة. راقب الأصناف بطيئة الحركة وحد التنبيه."),
    (("تكلفة البضاعة", "cogs"), "تكلفة البضاعة المباعة هي تكلفة الأصناف التي تم بيعها. تظهر كمصروف في قائمة الدخل وتساعد على حساب مجمل الربح."),
    (("مجمل الربح", "هامش الربح"), "مجمل الربح = المبيعات - تكلفة البضاعة المباعة. والهامش = مجمل الربح ÷ المبيعات. إذا انخفض الهامش راجع الخصومات والتكلفة وأسعار البيع."),
    (("صافي الربح", "الربح الصافي"), "صافي الربح = الإيرادات - كل المصروفات. لا يعني دائما توفر النقد، لذلك قارنه بالتدفق النقدي والتحصيل من العملاء."),
    (("نقطة التعادل", "تعادل"), "نقطة التعادل هي مستوى المبيعات الذي يغطي التكاليف دون ربح أو خسارة. تساعد في تحديد الحد الأدنى للمبيعات المطلوبة."),
    (("ضريبة المدخلات", "ضريبة المخرجات"), "ضريبة المخرجات على المبيعات، وضريبة المدخلات على المشتريات. غالبا المستحق للهيئة = المخرجات - المدخلات، مع الالتزام باللوائح المحلية."),
    (("قفل شهري", "إقفال شهر"), "القفل الشهري يمنع تعديل أو ترحيل عمليات داخل شهر مغلق. استخدمه بعد مراجعة الفواتير والقيود والرواتب والسلف والتأكد من التوازن."),
    (("تسوية بنكية", "مطابقة البنك"), "التسوية البنكية تقارن رصيد البنك في النظام بكشف البنك، وتكشف الشيكات أو التحويلات المعلقة أو الرسوم غير المسجلة."),
    (("إهلاك", "استهلاك الأصول"), "الإهلاك يوزع تكلفة الأصل الثابت على عمره الإنتاجي. القيد غالبا: مدين مصروف إهلاك، دائن مجمع إهلاك."),
    (("مصروف مقدم", "إيراد مقدم"), "المصروف المقدم أصل لأنه دفع لخدمة مستقبلية، والإيراد المقدم التزام لأنه قبض قبل تقديم الخدمة. تتم تسويتهما مع مرور الوقت."),
    (("مخصص", "ديون مشكوك"), "المخصص تقدير لمخاطر أو خسائر متوقعة مثل الديون المشكوك في تحصيلها. يساعد على عرض الأصول بشكل أكثر تحفظا."),
    (("رقابة داخلية", "مراجعة داخلية"), "الرقابة الداخلية تعني فصل المهام، اعتماد العمليات، مراجعة القيود، وتقييد الصلاحيات. في النظام استخدم الصلاحيات والتقارير غير المرحلة لكشف الخلل مبكرا."),
    (("صلاحيات", "صلاحية"), "الصلاحيات تحدد ما يراه المستخدم وما يستطيع إضافته أو تعديله أو حذفه. إذا لم تظهر صفحة أو زر فغالبا الحساب لا يملك الصلاحية أو الفرع غير مصرح له."),
    (("فرع", "فروع"), "بيانات النظام مرتبطة بالفرع المحدد. إذا كان دور المستخدم مقيدا بفرع واحد فلن يستطيع فتح أو تحليل بيانات فروع أخرى."),
    (("فاتورة شراء", "شراء"), "فاتورة الشراء الصحيحة تحتوي المورد، الرقم، التاريخ، الأصناف، الكميات، الأسعار، الضريبة، والإجمالي. بعد الحفظ يزيد المخزون وينشأ أثر محاسبي متوازن."),
    (("فاتورة بيع", "بيع"), "فاتورة البيع تسجل الإيراد والضريبة وتخفض المخزون وتثبت تكلفة البضاعة عند الترحيل. طريقة الدفع تحدد هل المدين صندوق/بنك أم عملاء."),
    (("رواتب", "راتب"), "الدورة الأفضل للرواتب مرحلتان: اعتماد الراتب لإثبات المصروف والرواتب المستحقة، ثم دفع الراتب لتخفيض الرواتب المستحقة والنقدية أو البنك."),
    (("سلفة", "سلف"), "السلفة للموظف تثبت كأصل باسم سلف الموظفين، وعند خصمها من الراتب ينخفض رصيد السلفة. لا ينبغي خصم أكثر من الرصيد المفتوح."),
    (("عمليات غير مرحلة", "غير مرحل"), "العمليات غير المرحلة هي سجلات بلا قيد محاسبي مرتبط. راجعها قبل التقارير الشهرية لأنها قد تجعل النتائج ناقصة."),
]


LOCAL_BUSINESS_ENCYCLOPEDIA = [
    (
        ("كاشير", "pos", "نقطة بيع", "نقاط البيع", "بيع نقدي"),
        "الكاشير الجيد يربط كل عملية بيع بالمخزون والضريبة وطريقة الدفع فورا. راقب إغلاق الوردية، الفروقات بين النقد الفعلي والنظام، المرتجعات، الخصومات اليدوية، والمبيعات الملغاة لأنها أكثر مواضع الخطأ أو التلاعب.",
    ),
    (
        ("تسعير", "السعر", "هامش", "خصم", "عروض"),
        "التسعير يبدأ من التكلفة الكاملة ثم هامش الربح المستهدف ثم مقارنة السوق. لا تجعل الخصم يأكل الهامش: احسب الهامش بعد الخصم والضريبة والعمولات والشحن، وحدد حد خصم يحتاج موافقة مدير.",
    ),
    (
        ("تدفق نقدي", "سيولة", "cash flow"),
        "إدارة السيولة أهم من الربح المحاسبي اليومي. قارن التحصيل المتوقع من العملاء مع المدفوعات للموردين والرواتب والضريبة خلال 30 و60 و90 يوما، وضع إنذارا مبكرا عندما تنخفض التغطية النقدية عن مصروفات شهر.",
    ),
    (
        ("استثمار", "عائد الاستثمار", "roi", "مخاطرة"),
        "قرار الاستثمار التجاري يحتاج حساب العائد المتوقع، مدة استرداد رأس المال، أثره على السيولة، وسيناريو متحفظ عند انخفاض المبيعات أو ارتفاع التكلفة. لا تعتمد على الربح المتوقع وحده بدون اختبار مخاطر السوق.",
    ),
    (
        ("مشروع", "إدارة مشاريع", "project management", "خطة مشروع"),
        "إدارة المشروع ماليا تعني ربط الميزانية بالمهام والمراحل. تابع الانحراف بين التكلفة المخططة والفعلية، نسبة الإنجاز، الالتزامات غير المفوترة، والمخاطر التي قد تؤخر التحصيل أو تزيد المصروف.",
    ),
    (
        ("السوق السعودي", "السعودية", "تجارة سعودية", "منشأة سعودية"),
        "في السوق السعودي انتبه لضريبة القيمة المضافة، الفوترة الإلكترونية، مواسم الطلب، تكاليف العمالة والإيجار، وسلوك الدفع بين القطاعات. النصيحة المالية يجب أن تراعي النشاط والمدينة والموسمية وحجم المنشأة.",
    ),
    (
        ("مؤشرات", "kpi", "مؤشر أداء", "لوحة مؤشرات"),
        "أهم مؤشرات الإدارة: نمو المبيعات، مجمل الربح، صافي الربح، دوران المخزون، متوسط أيام التحصيل، متوسط أيام السداد، نسبة المرتجعات، فرق الكاشير، وحصة أعلى العملاء والمنتجات من الإيراد.",
    ),
    (
        ("مخزون", "جرد", "دوران المخزون", "حد الطلب"),
        "المخزون يربط رأس المال بالمبيعات. صنف المنتجات إلى سريعة وبطيئة الحركة، حدد حد إعادة الطلب، راقب الأصناف الراكدة والقريبة من النفاد، ولا ترفع الشراء لمجرد ارتفاع المبيعات إذا كان الهامش أو السيولة ضعيفا.",
    ),
    (
        ("رقابة", "صلاحيات", "اعتماد", "موافقة"),
        "الرقابة العملية تعني أن الإضافة أو التعديل المؤثر محاسبيا يحتاج صلاحية وموافقة واضحة. الأفضل أن ينشئ الذكاء الاصطناعي مسودة، يشرح أثرها المحاسبي، ثم لا يحفظها إلا بعد تأكيد المستخدم المخول.",
    ),
    (
        ("ضريبة", "vat", "فاتورة إلكترونية", "زاتكا"),
        "لضريبة القيمة المضافة والفوترة الإلكترونية تأكد من بيانات العميل أو المورد، الرقم الضريبي عند الحاجة، تاريخ الفاتورة، بنود الضريبة، الإجمالي، وحالة الربط أو الإرسال. أي خطأ في الضريبة يؤثر على الإقرار والتقارير.",
    ),
    (
        ("تحليل مالي", "نصيحة مالية", "الوضع المالي"),
        "النصيحة المالية الدقيقة تبدأ من قراءة المبيعات والمشتريات والمخزون والنقد والديون والرواتب والعمليات غير المرحلة. بعد ذلك قارن بالفترة السابقة وحدد السبب المحتمل، ثم اقترح إجراء قابل للتنفيذ.",
    ),
    (
        ("تجارة", "بزنس", "business", "نمو"),
        "نمو التجارة لا يعني زيادة البيع فقط. راقب جودة الربح، قدرة المخزون على الدوران، تكلفة اكتساب العميل، الالتزام الضريبي، التحصيل، وخدمة العملاء. النمو الصحي يزيد الإيراد والسيولة معا بدون تضخم الديون.",
    ),
]


def local_greeting_or_concept_answer(question):
    normalized = (question or "").strip().lower()
    if _detect_user_language(question) == "en" and normalized in {"hello", "hi", "hey"}:
        return "Hello. I am your accounting assistant inside the system. I can help with invoices, journal entries, payroll, advances, reports, system navigation, and accounting explanations."
    simple_fact = _simple_general_fact_answer(question)
    if simple_fact:
        return simple_fact
    if _calculation_needs_more_numbers(question):
        return "أرسل العملية الحسابية أو الأرقام المطلوبة بوضوح. مثال: احسب 1500 + 375، أو احسب ضريبة 15% على 2000."
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
    matches.extend(answer for words, answer in LOCAL_PROFESSIONAL_KNOWLEDGE if any(word.lower() in normalized for word in words))
    matches.extend(answer for words, answer in LOCAL_BUSINESS_ENCYCLOPEDIA if any(word.lower() in normalized for word in words))
    if not matches:
        return ""
    return "\n".join(f"- {answer}" for answer in dict.fromkeys(matches))


def _is_light_conversation_question(question):
    normalized = (question or "").strip().lower()
    if not normalized:
        return False
    if normalized in {word.lower() for word in LOCAL_GREETING_PATTERNS}:
        return True
    if len(normalized) <= 35 and any(word in normalized for word in LOCAL_GREETING_PATTERNS):
        return True
    return any(any(word in normalized for word in words) for words, _answer in LOCAL_GENERAL_CHAT)


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


def normalize_user_question_text(question):
    text = re.sub(r"\s+", " ", (question or "")).strip()
    if not text:
        return ""
    for old, new in SPEECH_NORMALIZATION_REPLACEMENTS.items():
        text = re.sub(rf"(?<!\w){re.escape(old)}(?!\w)", new, text, flags=re.IGNORECASE)
    text = re.sub(r"[؟?]{2,}", "؟", text)
    return text.strip()


def _is_system_usage_question(question):
    normalized = normalize_user_question_text(question).lower()
    usage_markers = (
        "كيف", "طريقة", "استخدم", "استخدام", "أستخدم", "افتح", "اذهب", "اضافة",
        "إضافة", "أضف", "انشئ", "أنشئ", "وين", "أين", "شرح النظام",
    )
    return any(marker.lower() in normalized for marker in usage_markers)


def _simple_general_fact_answer(question):
    normalized = normalize_user_question_text(question).lower()
    if any(term in normalized for term in ("كم عدد أيام الأسبوع", "كم عدد ايام الاسبوع", "كم يوم في الأسبوع", "كم يوم في الاسبوع", "عدد أيام الاسبوع", "عدد ايام الاسبوع", "عدد أيام الأسبوع")):
        return "عدد أيام الأسبوع سبعة أيام: السبت، الأحد، الاثنين، الثلاثاء، الأربعاء، الخميس، الجمعة."
    if any(term in normalized for term in ("كم عدد شهور السنة", "كم شهر في السنة", "عدد أشهر السنة", "عدد شهور السنة")):
        return "عدد شهور السنة اثنا عشر شهرا."
    if any(term in normalized for term in ("كم ساعة في اليوم", "عدد ساعات اليوم")):
        return "اليوم يتكوّن من 24 ساعة."
    return ""


def _requests_accounting_data_or_analysis(question):
    normalized = normalize_user_question_text(question).lower()
    if _simple_general_fact_answer(normalized):
        return False
    data_markers = (
        "حلل", "تحليل", "قيّم", "قيم", "أداء", "اداء", "تفاصيل", "كم", "عدد",
        "إجمالي", "اجمالي", "رصيد", "تقرير", "مبيعات", "مشتريات", "فاتورة",
        "فواتير", "مخزون", "منتجات", "أصناف", "اصناف", "رواتب", "سلف",
        "فرع", "الفرع", "ربح", "خسارة", "ضريبة", "غير مرحلة", "غير المرحلة",
    )
    return any(marker in normalized for marker in data_markers)


def _classify_question_intent(question):
    normalized = normalize_user_question_text(question).lower()
    if not normalized:
        return "empty"
    if _is_light_conversation_question(question):
        return "conversation"
    explanation_terms = ("اشرح", "ما هو", "ما هي", "ما معنى", "لماذا", "عرف", "تعريف", "وضح")
    if any(term in normalized for term in explanation_terms) and local_greeting_or_concept_answer(question):
        return "explanation"
    if _calculation_needs_more_numbers(question) or re.search(r"\d", normalized):
        return "calculation"
    if _is_system_usage_question(question):
        return "system_usage"
    if _requests_accounting_data_or_analysis(question):
        return "accounting_analysis"
    if _is_general_web_question(question):
        return "web_research"
    return "general"


def _answer_core_for_confidence(answer=""):
    text = (answer or "").strip()
    style_markers = (
        "الخلاصة مباشرة:",
        "بصياغة عملية:",
        "الجواب المختصر:",
        "خلينا نرتبها بوضوح:",
        "Here is the clean answer:",
        "A practical way to read it:",
        "Short version first:",
        "Let me frame it clearly:",
    )
    for marker in style_markers:
        if text.startswith(marker):
            text = text[len(marker):].strip()
            break
    closer_markers = (
        "لو تريد نتيجة أدق",
        "أستطيع تحويلها إلى خطوات تنفيذية",
        "للتوسع أكثر",
        "Next, I can narrow this",
        "For a sharper result",
        "I can also turn this",
    )
    for marker in closer_markers:
        index = text.find(marker)
        if index > 0:
            text = text[:index].strip()
    return text


def _answer_confidence_for_source(source, answer=""):
    answer = _answer_core_for_confidence(answer)
    if source in {"accounting_data", "local_calculator", "permissions", "zatca_regulations"}:
        return "high"
    if source in {"free_web", "local_knowledge", "local", "local_strong"}:
        return "medium"
    if source == "private":
        return "medium" if len((answer or "").strip()) >= 120 else "low"
    if source in {"clarification", "islamic_policy"}:
        return "high"
    return "low"


def _quality_notice(intent, source, confidence):
    if source == "clarification":
        return ""
    if confidence == "low":
        return "ملاحظة جودة: الإجابة المتاحة محدودة؛ أرسل تفاصيل أكثر أو حدّد النطاق لأعطيك نتيجة أدق."
    if intent == "accounting_analysis" and source not in {"accounting_data", "local_strong", "private", "permissions"}:
        return "ملاحظة جودة: لم أجد بيانات كافية من النظام لهذا السؤال؛ اعتبر الرد إرشادا عاما لا تحليلا نهائيا."
    if intent == "web_research" and source != "free_web":
        return "ملاحظة جودة: لم أجد مصدرا خارجيا كافيا؛ راجع مصدرا رسميا إذا كان القرار مهما."
    return ""


def _finalize_ai_result(result, question):
    result = dict(result or {})
    answer = result.get("answer") or result.get("message") or ""
    source = result.get("source", "")
    intent = _classify_question_intent(question)
    confidence = _answer_confidence_for_source(source, answer)
    result["intent"] = intent
    result["confidence"] = confidence
    if answer:
        notice = _quality_notice(intent, source, confidence)
        if notice and notice not in answer:
            answer = f"{answer.rstrip()}\n\n{notice}"
        result["answer"] = answer
    return result


def _answer_looks_irrelevant(question, answer):
    normalized_question = (question or "").strip().lower()
    normalized_answer = (answer or "").strip().lower()
    if not normalized_question or not normalized_answer:
        return False
    if _is_light_conversation_question(question) and any(marker in normalized_answer for marker in (
        "تحليل احترافي", "الملخص التنفيذي", "المبيعات:", "المشتريات:", "هامش الربح",
    )):
        return True
    if normalized_question in {"أهلا", "اهلا", "مرحبا", "هلا", "hi", "hello"} and len(normalized_answer) > 700:
        return True
    return False


def _repair_irrelevant_answer(question, answer):
    local_answer = local_greeting_or_concept_answer(question)
    if local_answer:
        return _polish_answer(local_answer, question)
    ambiguous = local_ambiguous_request_answer(question)
    if ambiguous:
        return _polish_answer(ambiguous, question)
    return "فهمت أن الرد السابق لم يطابق سؤالك. اكتب السؤال بصيغة مباشرة أو حدّد هل تريد شرحا، بحثا في النت، أو تحليلا من بيانات النظام."


def _analyze_user_question(question):
    normalized_text = normalize_user_question_text(question)
    normalized = normalized_text.lower()
    intent = _classify_question_intent(normalized_text)
    explanation_terms = ("اشرح", "ما هو", "ما هي", "ما معنى", "لماذا", "عرف", "تعريف", "وضح")
    execution_terms = (
        "افتح", "اذهب", "اعرض", "أظهر", "انتقل", "نفذ", "أضف", "اضف",
        "أنشئ", "انشئ", "سجل", "احفظ", "بيع", "كاشير", "تأكيد",
    )
    needs_explanation = any(term in normalized for term in explanation_terms)
    asks_execution = any(term in normalized for term in execution_terms) and not needs_explanation
    asks_research = _is_general_web_question(normalized_text)
    asks_company_data = _requests_accounting_data_or_analysis(normalized_text)
    return {
        "intent": intent,
        "normalized_text": normalized_text,
        "needs_explanation": needs_explanation,
        "asks_execution": asks_execution,
        "asks_research": asks_research,
        "asks_company_data": asks_company_data,
    }


def _should_try_execution(question_analysis):
    return bool(question_analysis.get("asks_execution")) and question_analysis.get("intent") not in {
        "conversation",
        "web_research",
        "general",
    }


def local_system_usage_answer(question):
    normalized = (question or "").strip().lower()
    matches = [answer for words, answer in SYSTEM_HELP_PATTERNS if any(word.lower() in normalized for word in words)]
    if not matches:
        return ""
    return "\n".join(f"- {answer}" for answer in dict.fromkeys(matches))


def _quality_followups(question, primary=None):
    normalized = (question or "").lower()
    followups = []
    if primary:
        followups.append(f"افتح {primary['title']}")
    if any(word in normalized for word in ("مبيعات", "بيع", "فاتورة")):
        followups.extend(["حلل مبيعات هذا الشهر", "اعرض فواتير البيع غير المرحلة"])
    if any(word in normalized for word in ("مشتريات", "شراء", "مورد")):
        followups.extend(["حلل المشتريات والموردين", "افتح فواتير الشراء"])
    if any(word in normalized for word in ("مخزون", "صنف", "منتج")):
        followups.extend(["ما الأصناف قليلة المخزون؟", "أضف صنف جديد"])
    if any(word in normalized for word in ("راتب", "رواتب", "سلفة", "موظف")):
        followups.extend(["افتح كشف الرواتب", "افتح كشف السلف"])
    if not followups:
        followups.extend(["حلل الوضع المالي", "كيف أستخدم النظام؟", "اشرح لي القيد المحاسبي"])
    unique = []
    for item in followups:
        if item not in unique:
            unique.append(item)
    return unique[:4]


def _style_variant_index(question="", buckets=4):
    seed = f"{question}|{timezone.now().timestamp()}".encode("utf-8", errors="ignore")
    return int(hashlib.sha256(seed).hexdigest()[:8], 16) % buckets


def _vary_answer_style(text, question="", language="ar", primary=None):
    stripped = (text or "").strip()
    if not stripped:
        return stripped
    if any(marker in stripped[:160] for marker in ("تأكيد", "إلغاء", "لا أستطيع", "أعتذر بلطف", "Permission", "Confirm", "Cancel")):
        return stripped
    if _simple_general_fact_answer(question):
        return stripped
    if len(stripped) > 1800:
        return stripped

    idx = _style_variant_index(question)
    if language == "en":
        intros = (
            "Here is the clean answer:",
            "A practical way to read it:",
            "Short version first:",
            "Let me frame it clearly:",
        )
        closers = (
            "",
            "\n\nNext, I can narrow this into numbers or actions if you give me the target period.",
            "\n\nFor a sharper result, specify the branch, period, or report you want me to use.",
            "\n\nI can also turn this into a step-by-step action plan inside the system.",
        )
    else:
        intros = (
            "الخلاصة مباشرة:",
            "بصياغة عملية:",
            "الجواب المختصر:",
            "خلينا نرتبها بوضوح:",
        )
        closers = (
            "",
            "\n\nلو تريد نتيجة أدق، حدد الفترة أو الفرع أو التقرير المطلوب.",
            "\n\nأستطيع تحويلها إلى خطوات تنفيذية داخل النظام عند الحاجة.",
            "\n\nللتوسع أكثر، اسألني عن السبب أو الأثر المحاسبي أو الإجراء التالي.",
        )

    if not any(stripped.startswith(intro) for intro in intros) and not stripped.startswith(("-", "•")):
        stripped = f"{intros[idx]}\n\n{stripped}"
    if primary is None and closers[idx] and len(stripped) < 900 and closers[idx].strip() not in stripped:
        stripped = f"{stripped.rstrip()}{closers[idx]}"
    return stripped


def _polish_answer(answer, question="", primary=None):
    text = _remove_performance_stage_directions(answer)
    language = _detect_user_language(question)
    if not text:
        text = "أبشر، أحتاج تفاصيل أكثر حتى أساعدك بدقة. اكتب المطلوب أو استخدم الصوت، وسأسألك عن أي معلومة ناقصة قبل التنفيذ."
    if language == "en":
        text = text.replace("الناتج =", "Result =").replace("ط§ظ„ظ†ط§طھط¬ =", "Result =")
        text = text.replace("أبشر، خلينا نخليها واضحة.", "Sure, let's make it clear.")
        text = text.replace("ط£ط¨ط´ط±طŒ ط®ظ„ظٹظ†ط§ ظ†ط®ظ„ظٹظ‡ط§ ظˆط§ط¶ط­ط©.", "Sure, let's make it clear.")
    needs_friendly_intro = (
        language == "ar"
        and len(text) < 120
        and not any(greeting in text[:80] for greeting in ("أهلا", "مرحبا", "أبشر", "تمام", "وعليكم", "تم ", "لا أستطيع"))
        and not text.startswith(("-", "•"))
    )
    if needs_friendly_intro:
        text = "أبشر، خلينا نخليها واضحة.\n\n" + text
    needs_followup_block = (
        len(text) < 700
        and "الخطوة التالية" not in text
        and "صلاحية" not in text
        and "تأكيد" not in text
        and "إلغاء" not in text
        and primary is not None
    )
    if needs_followup_block:
        followups = _quality_followups(question, primary)
        if followups:
            text += "\n\nالخطوة التالية المقترحة:\n" + "\n".join(f"- {item}" for item in followups[:2])
    return _vary_answer_style(text, question=question, language=language, primary=primary).strip()


ISLAMIC_POLICY_TERMS = (
    "الشريعة", "شرعي", "شرعية", "حكم", "حلال", "حرام", "فتوى", "يفتي", "افتاء",
    "الدين", "إسلام", "اسلام", "سنة", "بدعة", "المنهج السلفي", "سلفي",
    "ربا", "ربوي", "زكاة المال", "صلاة", "صوم", "حج", "عمرة",
    "قرآن", "القرآن", "حديث", "أهل العلم", "العلماء", "الشيخ",
)

ISLAMIC_POLICY_REGULATORY_EXCEPTIONS = (
    "هيئة الزكاة", "زاتكا", "zatca", "اللائحة", "لوائح", "نظام", "أنظمة",
    "ضريبة", "الضريبة", "الفوترة", "إقرار", "اقرار", "وعاء زكوي",
)


def _contains_policy_term(normalized, term):
    term = term.lower()
    if " " in term:
        return term in normalized
    return term in re.split(r"[^\w\u0600-\u06FF]+", normalized)


def islamic_policy_guard_answer(question):
    normalized = (question or "").strip().lower()
    if not normalized:
        return ""
    if "زكاة" in normalized and any(term in normalized for term in ISLAMIC_POLICY_REGULATORY_EXCEPTIONS):
        return ""
    if not any(_contains_policy_term(normalized, term) for term in ISLAMIC_POLICY_TERMS):
        return ""
    return "\n".join([
        "لا أستطيع تقديم فتوى أو حكم شرعي أو شرح لمسائل الشريعة الإسلامية.",
        "يرجى التواصل مع أهل العلم الموثوقين أو جهة إفتاء معتبرة في هذا الأمر.",
        "أستطيع مساعدتك فقط في الجانب المحاسبي أو الإداري أو التقني غير الشرعي من السؤال إذا رغبت.",
    ])


FREE_WEB_GENERAL_SOURCES = {
    "wikipedia": {
        "name": "Wikipedia",
        "license": "CC BY-SA؛ متاح للاستخدام التجاري مع النسبة والالتزام بشروط الترخيص.",
    },
    "wikidata": {
        "name": "Wikidata",
        "license": "CC0؛ بيانات مفتوحة قابلة لإعادة الاستخدام التجاري.",
    },
    "openalex": {
        "name": "OpenAlex",
        "license": "CC0؛ بيانات بحثية وفهرسية مفتوحة قابلة لإعادة الاستخدام التجاري.",
    },
    "duckduckgo": {
        "name": "DuckDuckGo Web Search",
        "license": "نتائج بحث وروابط إلى صفحات خارجية؛ راجع ترخيص ومحتوى كل مصدر أصلي.",
    }
}

ZATCA_OFFICIAL_REGULATIONS = [
    {
        "title": "اللائحة التنفيذية لنظام ضريبة القيمة المضافة",
        "url": "https://zatca.gov.sa/ar/RulesRegulations/Taxes/Pages/VATImplementingRegulations.aspx",
        "keywords": ("ضريبة القيمة المضافة", "القيمة المضافة", "vat", "ضريبة", "مدخلات", "مخرجات"),
        "note": "تشمل قواعد تنفيذ ضريبة القيمة المضافة ومتطلبات الامتثال الضريبي للمنشآت.",
    },
    {
        "title": "نظام ضريبة القيمة المضافة",
        "url": "https://zatca.gov.sa/ar/RulesRegulations/Taxes/Pages/VATLaw.aspx",
        "keywords": ("نظام ضريبة القيمة المضافة", "vat law", "نظام vat"),
        "note": "الإطار النظامي لضريبة القيمة المضافة في المملكة وفق الاتفاقية الموحدة لدول مجلس التعاون.",
    },
    {
        "title": "لائحة الفوترة الإلكترونية",
        "url": "https://zatca.gov.sa/ar/E-Invoicing/Introduction/LawsAndRegulations",
        "keywords": ("الفوترة الإلكترونية", "فاتورة إلكترونية", "زاتكا", "fatoorah", "e-invoicing", "qr"),
        "note": "اللائحة والضوابط والمتطلبات الفنية والقواعد الإجرائية للفوترة الإلكترونية.",
    },
    {
        "title": "دليل الفوترة الإلكترونية الفني التفصيلي",
        "url": "https://www.zatca.gov.sa/ar/E-Invoicing/Introduction/Guidelines/Documents/E-invoicing%20Detailed%20Technical%20Guidelines.pdf",
        "keywords": ("xml", "ubl", "sdk", "clearance", "reporting", "مواصفات فنية", "دليل فني"),
        "note": "مرجع فني للتكامل، التحقق، نماذج الإرسال، QR، وملفات XML للفواتير والإشعارات.",
    },
    {
        "title": "اللائحة التنفيذية لجباية الزكاة",
        "url": "https://zatca.gov.sa/ar/RulesRegulations/Zakat/Pages/default.aspx",
        "keywords": ("زكاة", "الزكاة", "جباية الزكاة", "وعاء زكوي"),
        "note": "مرجع قواعد جباية الزكاة ومتطلبات المكلفين الخاضعين للزكاة.",
    },
    {
        "title": "اللائحة التنفيذية للضريبة الانتقائية",
        "url": "https://www.zatca.gov.sa/ar/RulesRegulations/Taxes/Pages/ExciseTaxImplementingRegulations.aspx",
        "keywords": ("ضريبة انتقائية", "الانتقائية", "excise", "تبغ", "مشروبات محلاة"),
        "note": "قواعد السلع الانتقائية، احتساب الضريبة، الإقرار، والطوابع الضريبية.",
    },
    {
        "title": "اللائحة التنفيذية لنظام ضريبة التصرفات العقارية",
        "url": "https://zatca.gov.sa/ar/RulesRegulations/Taxes/Pages/New_RETT.aspx",
        "keywords": ("التصرفات العقارية", "ضريبة التصرفات", "real estate transaction tax", "rett", "عقار"),
        "note": "قواعد ضريبة التصرفات العقارية والاستثناءات والإجراءات المرتبطة بها.",
    },
    {
        "title": "صفحة الأنظمة واللوائح في هيئة الزكاة والضريبة والجمارك",
        "url": "https://zatca.gov.sa/ar/RulesRegulations/Pages/default.aspx",
        "keywords": ("لوائح الهيئة", "أنظمة الهيئة", "كل اللوائح", "جميع اللوائح", "zatca regulations"),
        "note": "الفهرس الرسمي الأشمل للأنظمة واللوائح والأدلة المنشورة من الهيئة.",
    },
]


def zatca_regulations_answer(question):
    normalized = (question or "").strip().lower()
    if not normalized:
        return ""
    zatca_terms = (
        "زاتكا", "هيئة الزكاة", "الضريبة والجمارك", "zatca", "الزكاة", "زكاة",
        "ضريبة القيمة", "vat", "الفوترة الإلكترونية", "فاتورة إلكترونية",
        "ضريبة انتقائية", "التصرفات العقارية", "لوائح الهيئة", "اللوائح",
    )
    if not any(term in normalized for term in zatca_terms):
        return ""
    wants_full_index = any(term in normalized for term in ("جميع", "كل", "كافة", "الفهرس", "all"))
    matches = [] if wants_full_index else [
        item for item in ZATCA_OFFICIAL_REGULATIONS
        if any(keyword.lower() in normalized for keyword in item["keywords"])
    ]
    if not matches:
        matches = ZATCA_OFFICIAL_REGULATIONS[:]
    else:
        index_page = ZATCA_OFFICIAL_REGULATIONS[-1]
        if index_page not in matches:
            matches.append(index_page)
    lines = [
        "هيئة الزكاة والضريبة والجمارك هي الجهة الحكومية المختصة في السعودية بإدارة الزكاة والضرائب والجمارك، ومن ضمن ذلك ضريبة القيمة المضافة والفوترة الإلكترونية واللوائح المرتبطة بها.",
        "",
        "أهم المراجع الرسمية:",
    ]
    for item in matches[:8]:
        lines.append(f"- {item['title']}: {item['note']}")
        lines.append(f"  {item['url']}")
    lines.append("")
    lines.append("تنبيه مهني: عند اتخاذ قرار ضريبي أو زكوي، اعتمد على آخر نص رسمي منشور أو راجع مختصا مرخصا.")
    return "\n".join(lines)


GENERAL_WEB_TRIGGERS = (
    "ابحث",
    "بحث",
    "ابحث في النت",
    "ابحث في الإنترنت",
    "النت",
    "الإنترنت",
    "من هو",
    "من هي",
    "ما هو",
    "ما هي",
    "ما معنى",
    "اشرح",
    "فسر",
    "عرّف",
    "متى",
    "أين",
    "اين",
    "عرفني على",
    "معلومات عن",
    "اشرح لي عن",
    "حلل معلومات",
    "حلل لي",
    "قارن",
    "مقارنة",
    "مصادر",
    "المصدر",
    "أحدث",
    "احدث",
    "آخر",
    "اخر",
    "حالي",
    "حالياً",
    "اليوم",
    "الآن",
    "who is",
    "what is",
    "when is",
    "where is",
    "search",
    "research",
    "explain",
    "define",
    "compare",
    "sources",
    "latest",
    "current",
    "today",
    "now",
)

GENERAL_KNOWLEDGE_TERMS = (
    "علم", "علمي", "علوم", "فيزياء", "كيمياء", "أحياء", "طب", "تاريخ", "جغرافيا",
    "رياضيات", "تقنية", "كمبيوتر", "ذكاء اصطناعي", "فضاء", "كوكب", "صحة",
    "اقتصاد", "إدارة", "ادارة", "قانون", "تعليم", "ثقافة", "سياسة", "لغة",
    "برمجة", "أمن سيبراني", "بيانات", "تحليل", "دراسة", "بحث", "مصادر",
    "science", "physics", "chemistry", "biology", "medicine", "history", "geography",
    "math", "technology", "computer", "ai", "space", "planet", "health",
    "economics", "management", "law", "education", "culture", "programming",
    "cybersecurity", "data", "analysis", "research",
)

SYSTEM_OR_COMPANY_TERMS = (
    "فاتورة",
    "فواتير",
    "مبيعات",
    "مشتريات",
    "مخزون",
    "راتب",
    "رواتب",
    "سلفة",
    "سلف",
    "قيد",
    "قيود",
    "تقرير",
    "تقارير",
    "الشركة",
    "الشركات",
    "شركتي",
    "شركاتي",
    "فرع",
    "الفروع",
    "فروعي",
    "النظام",
    "المحاسبة",
    "محاسبي",
    "مدين",
    "دائن",
    "ضريبة",
    "vat",
    "invoice",
    "sales",
    "purchase",
    "inventory",
    "salary",
    "journal",
)

COMPANY_DATA_TERMS = (
    "شركتي",
    "الشركة",
    "شركاتي",
    "الشركات",
    "فرعي",
    "الفرع",
    "فروعي",
    "الفروع",
    "فواتيري",
    "فاتورتي",
    "عملائي",
    "موردي",
    "مخزوني",
    "منتجاتي",
    "رواتبي",
    "موظفيني",
    "تقاريري",
    "عندي",
    "لدينا",
    "في النظام",
    "في الفرع",
    "my company",
    "my invoices",
    "my inventory",
    "our sales",
)


def _free_web_answers_enabled():
    return bool(getattr(settings, "ENABLE_FREE_WEB_ANSWERS", True))


def _ai_auto_knowledge_enabled():
    return bool(getattr(settings, "ENABLE_AI_AUTO_KNOWLEDGE", True))


def _summarize_interaction_text(text, limit=240):
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    clean = re.sub(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", "[email]", clean)
    clean = re.sub(r"\b(?:\+?\d[\d\s\-]{7,}\d)\b", "[number]", clean)
    return clean[:limit]


USER_MEMORY_TRIGGERS = (
    "تذكر", "احفظ", "خزن", "سجل معلومة", "معلومة مهمة", "للمستقبل",
    "remember", "save this", "note that",
)


def _extract_user_memory_text(question):
    text = re.sub(r"\s+", " ", (question or "")).strip()
    if not text:
        return ""
    normalized = text.lower()
    if not any(trigger in normalized for trigger in USER_MEMORY_TRIGGERS):
        return ""
    cleaned = re.sub(
        r"^(تذكر|احفظ|خزن|سجل\s+معلومة|معلومة\s+مهمة|للمستقبل|remember|save\s+this|note\s+that)[:\s،-]*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if len(cleaned) < 8:
        return ""
    return _summarize_interaction_text(cleaned, limit=700)


def _user_memory_source():
    source, _created = AIKnowledgeSource.objects.get_or_create(
        url="app://user-memory",
        defaults={
            "name": "ذاكرة المستخدم داخل النظام",
            "license_note": "معلومات أدخلها المستخدم صراحة للاستفادة منها لاحقا.",
        },
    )
    return source


def remember_user_information(branch_id, user, question):
    memory_text = _extract_user_memory_text(question)
    if not memory_text:
        return None
    user_id = getattr(user, "id", None) if getattr(user, "is_authenticated", False) else "anonymous"
    content = f"user:{user_id}|branch:{branch_id}|{memory_text}"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    title = f"معلومة من المستخدم {user_id}"
    entry, _created = AIKnowledgeEntry.objects.update_or_create(
        content_hash=content_hash,
        defaults={
            "source": _user_memory_source(),
            "title": title,
            "summary": memory_text,
            "source_url": "app://user-memory",
            "topic": f"user_memory:{user_id}:branch:{branch_id or 'all'}",
            "is_approved": True,
        },
    )
    return entry


def record_ai_interaction_learning(branch_id, user, question, result, feedback=""):
    if not getattr(settings, "ENABLE_AI_INTERACTION_LEARNING", True):
        return None
    try:
        remember_user_information(branch_id, user, question)
        return AIInteractionLearning.objects.create(
            branch_id=branch_id,
            user=user if getattr(user, "is_authenticated", False) else None,
            question_summary=_summarize_interaction_text(question),
            answer_source=(result or {}).get("source", ""),
            user_feedback=feedback[:20] if feedback else "",
            improvement_note="auto-captured summary for admin review",
        )
    except Exception:
        return None


def search_local_knowledge_entries(question, limit=4, user=None, branch_id=None):
    if not _ai_auto_knowledge_enabled():
        return []
    normalized = (question or "").strip().lower()
    if not normalized:
        return []
    words = [word for word in re.split(r"[^\w\u0600-\u06FF]+", normalized) if len(word) >= 3]
    entries = AIKnowledgeEntry.objects.filter(is_approved=True).select_related("source")[:120]
    scored = []
    for entry in entries:
        haystack = f"{entry.title} {entry.topic} {entry.summary}".lower()
        score = sum(1 for word in words if word in haystack)
        user_id = getattr(user, "id", None) if getattr(user, "is_authenticated", False) else None
        if user_id and f"user_memory:{user_id}:" in entry.topic:
            score += 3
        if branch_id and f"branch:{branch_id}" in entry.topic:
            score += 2
        if score:
            scored.append((score, entry))
    return [entry for score, entry in sorted(scored, key=lambda row: row[0], reverse=True)[:limit]]


def local_knowledge_answer(question, user=None, branch_id=None):
    entries = search_local_knowledge_entries(question, user=user, branch_id=branch_id)
    if not entries:
        return ""
    lines = ["وفق المعرفة المتاحة داخل النظام:"]
    for entry in entries:
        lines.append(f"- {entry.title}: {entry.summary}")
    lines.append("ملاحظة مهنية: عند القرارات النظامية أو المالية الحساسة، راجع النص الرسمي الأحدث.")
    return "\n".join(lines)


def _calculation_needs_more_numbers(question):
    normalized = (question or "").strip().lower()
    if not any(word in normalized for word in ("احسب", "حساب", "calculate")):
        return False
    return not re.search(r"\d", normalized)


def _safe_decimal_text(value):
    text = f"{_money(value)}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _safe_eval_math_expression(expression):
    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise ZeroDivisionError
            return left / right
        raise ValueError

    return evaluate(ast.parse(expression, mode="eval"))


def local_calculation_answer(question):
    normalized = (question or "").strip().lower()
    has_math_expression = bool(re.fullmatch(r"\s*\d+(?:[.,]\d+)?\s*[+\-*/]\s*\d+(?:[.,]\d+)?(?:\s*[+\-*/]\s*\d+(?:[.,]\d+)?)*\s*", normalized))
    if not has_math_expression and not any(word in normalized for word in ("احسب", "حساب", "calculate", "كم يساوي", "ط§ط­ط³ط¨", "ط­ط³ط§ط¨", "ظƒظ… ظٹط³ط§ظˆظٹ")):
        return ""
    numbers = [Decimal(match.replace(",", ".")) for match in re.findall(r"\d+(?:[.,]\d+)?", normalized)]
    if not numbers:
        return ""
    if any(term in normalized for term in ("ضريبة", "vat", "%", "نسبة", "percent")):
        if "%" in normalized and len(numbers) > 1:
            rate = numbers[0]
            base = numbers[1]
        else:
            base = numbers[0]
            rate = numbers[1] if len(numbers) > 1 else Decimal("15")
        tax = base * rate / Decimal("100")
        total = base + tax
        return "\n".join([
            f"قيمة الضريبة {rate}% على {_safe_decimal_text(base)} = {_safe_decimal_text(tax)}.",
            f"الإجمالي شامل الضريبة = {_safe_decimal_text(total)}.",
        ])
    expression = normalized
    replacements = {
        "×": "*", "x": "*", "÷": "/", "زائد": "+", "ناقص": "-", "ضرب": "*", "في": "*", "على": "/",
    }
    for old, new in replacements.items():
        expression = expression.replace(old, new)
    expression = re.sub(r"[^0-9+\-*/(). ]", " ", expression)
    expression = re.sub(r"\s+", "", expression)
    if not re.search(r"[+\-*/]", expression):
        return f"الرقم الذي أرسلته هو {_safe_decimal_text(numbers[0])}. إذا أردت عملية حسابية اكتبها مثل: احسب {numbers[0]} + 25."
    if not re.fullmatch(r"[0-9+\-*/().]+", expression):
        return ""
    try:
        result = _safe_eval_math_expression(expression)
    except Exception:
        return "لم أستطع فهم العملية الحسابية. اكتبها بصيغة واضحة مثل: احسب 1500 + 375 أو احسب ضريبة 15% على 2000."
    return f"الناتج = {_safe_decimal_text(result)}."


def local_ambiguous_request_answer(question):
    normalized = (question or "").strip().lower()
    short_commands = {"حلل", "احسب", "افتح", "اعرض", "ساعدني", "تقرير", "بيع", "شراء"}
    if normalized in short_commands:
        if normalized in {"احسب"}:
            return "أرسل الأرقام أو العملية الحسابية المطلوبة بوضوح. مثال: احسب 1500 + 375، أو احسب ضريبة 15% على 2000."
        return "\n".join([
            "اكتب المطلوب بتفصيل بسيط حتى أعطيك نتيجة دقيقة.",
            "أمثلة:",
            "- احسب ضريبة 15% على 2000",
            "- حلل مبيعات هذا الشهر",
            "- أنشئ عرض سعر للعميل أحمد 2 Item",
            "- بيع 2 Item كاشير",
        ])
    return ""


def _remove_performance_stage_directions(answer):
    text = (answer or "").strip()
    if not text:
        return text
    blocked_patterns = (
        r"^ابتسامة[^:：]*[:：]\s*",
        r"^نبرة[^:：]*[:：]\s*",
        r"^بابتسامة[^:：]*[:：]?\s*",
        r"^\([^)]*(ابتسامة|نبرة|يبتسم|بهدوء)[^)]*\)\s*",
    )
    for pattern in blocked_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
    if "المحاسب لا يخاف من الدائن" in text:
        return "أرسل العملية الحسابية أو السؤال المطلوب بوضوح، وسأجيبك مباشرة بدون عبارات تمثيلية."
    return text


def upsert_ai_knowledge_entry(source, title, summary, source_url, topic=""):
    content = f"{source_url}|{title}|{summary}"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    entry, _ = AIKnowledgeEntry.objects.update_or_create(
        content_hash=content_hash,
        defaults={
            "source": source,
            "title": title[:300],
            "summary": summary[:2000],
            "source_url": source_url[:700],
            "topic": topic[:120],
            "is_approved": True,
        },
    )
    return entry


def _is_general_web_question(question):
    normalized = (question or "").strip().lower()
    if not normalized:
        return False
    if any(term in normalized for term in COMPANY_DATA_TERMS):
        return False
    if any(trigger in normalized for trigger in GENERAL_WEB_TRIGGERS):
        return True
    if any(term in normalized for term in GENERAL_KNOWLEDGE_TERMS):
        return True
    return bool(len(normalized.split()) >= 2 and any(term in normalized for term in (
        "ifrs", "gaap", "زكاة", "ضريبة", "قيمة مضافة", "محاسبة", "ادارة مشاريع", "إدارة مشاريع",
        "تجارة", "تسويق", "مخزون", "سلاسل الامداد", "سلاسل الإمداد", "cash flow", "inventory",
        "accounting", "project management", "marketing", "supply chain",
        "كاشير", "نقطة بيع", "نقاط البيع", "استثمار", "تسعير", "تدفق نقدي", "تحليل مالي", "السوق السعودي", "بزنس", "business",
    )))


def _wikipedia_language(question):
    text = question or ""
    if re.search(r"[\u0980-\u09FF]", text):
        return "bn"
    if re.search(r"[پچژگٹڈڑںے]", text):
        return "ur"
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    return "en"


def _clean_general_web_query(question):
    cleaned = (question or "").strip()
    cleaned = re.sub(
        r"^(ابحث\s+عن|ابحث|من\s+هو|من\s+هي|ما\s+هو|ما\s+هي|معلومات\s+عن|عرفني\s+على|اشرح\s+لي\s+عن)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^(who\s+is|what\s+is|when\s+is|where\s+is)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ؟?،,.") or (question or "").strip()


def _question_needs_current_source_warning(question):
    normalized = (question or "").strip().lower()
    current_markers = (
        "أحدث", "احدث", "آخر", "اخر", "حالي", "حالياً", "الآن", "اليوم", "هذا الأسبوع",
        "الأخبار", "اخبار", "سعر", "أسعار", "قانون جديد", "نظام جديد", "إصدار", "نسخة",
        "latest", "current", "today", "now", "news", "price", "version", "release",
    )
    return any(marker in normalized for marker in current_markers)


GEOGRAPHY_TERMS = (
    "جغرافيا", "جغرافي", "دولة", "الدول", "بلد", "مدينة", "قرية", "عاصمة", "قارة",
    "موقع", "أين تقع", "اين تقع", "حدود", "تحدها", "مساحة", "سكان", "تضاريس",
    "مناخ", "إقليم", "محافظة", "منطقة", "بحر", "محيط", "نهر", "جبل", "جزيرة",
    "إحداثيات", "احداثيات", "خط العرض", "خط الطول",
    "geography", "country", "city", "capital", "continent", "location", "border",
    "population", "area", "climate", "river", "mountain", "island", "coordinates",
    "latitude", "longitude",
)


def _is_geography_question(question):
    normalized = normalize_user_question_text(question or "").strip().lower()
    return any(term in normalized for term in GEOGRAPHY_TERMS)


def _clean_geography_place_query(question):
    query = normalize_user_question_text(question or "").strip()
    patterns = (
        r"^(?:ما|ماذا|أين|اين|كم|اذكر|اشرح|عرّف|عرف)\s+",
        r"\b(?:هي|هو|تقع|موقع|عاصمة|دولة|مدينة|بلد|عدد سكان|مساحة|حدود|إحداثيات|احداثيات)\b",
        r"\b(?:what|where|is|the|capital|country|city|population|area|borders|coordinates|of)\b",
    )
    for pattern in patterns:
        query = re.sub(pattern, " ", query, flags=re.IGNORECASE)
    query = re.sub(r"\s+", " ", query).strip(" ؟?،,.")
    return query or _clean_general_web_query(question)


def _nominatim_geography_facts(question):
    if not _free_web_answers_enabled() or not _is_geography_question(question):
        return {}
    query = _clean_geography_place_query(question)
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": 1,
                "accept-language": _wikipedia_language(question),
            },
            headers={"User-Agent": "AccountingSystemAI/1.0 geographic assistant"},
            timeout=7,
        )
        response.raise_for_status()
        rows = response.json()
    except (requests.RequestException, ValueError, TypeError):
        return {}
    if not rows:
        return {}
    row = rows[0]
    display_name = (row.get("display_name") or query).strip()
    latitude = row.get("lat")
    longitude = row.get("lon")
    place_type = row.get("type") or row.get("category") or "مكان"
    details = [f"{display_name}؛ التصنيف الجغرافي: {place_type}"]
    if latitude and longitude:
        details.append(f"الإحداثيات التقريبية: خط العرض {latitude}، وخط الطول {longitude}")
    return {
        "title": display_name,
        "extract": "، ".join(details) + ".",
        "source_url": f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}" if latitude and longitude else "",
        "source_name": "OpenStreetMap Nominatim",
        "license": "OpenStreetMap data, ODbL",
        "kind": "geography",
    }


def _source_reliability_score(source):
    name = (source.get("source_name") or "").lower()
    url = (source.get("source_url") or "").lower()
    score = 50
    if "wikipedia" in name:
        score += 15
    if "wikidata" in name:
        score += 12
    if "openalex" in name:
        score += 18
    if "openstreetmap" in name or "nominatim" in name:
        score += 20
    if "duckduckgo" in name:
        score += 8
    if ".gov" in url or "zatca.gov.sa" in url:
        score += 25
    if "doi.org" in url or "openalex.org" in url:
        score += 10
    if not source.get("extract"):
        score -= 20
    return max(0, min(score, 100))


def _source_reliability_label(score):
    if score >= 80:
        return "عالية"
    if score >= 60:
        return "متوسطة"
    return "محدودة"


def _wikipedia_summary(question):
    if not _free_web_answers_enabled() or not _is_general_web_question(question):
        return {}

    lang = _wikipedia_language(question)
    query = _clean_general_web_query(question)
    headers = {"User-Agent": "AccountingSystemAI/1.0 (free-commercial-source: Wikipedia CC BY-SA)"}
    try:
        search_response = requests.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "opensearch",
                "search": query,
                "limit": 1,
                "namespace": 0,
                "format": "json",
            },
            headers=headers,
            timeout=6,
        )
        search_response.raise_for_status()
        search_data = search_response.json()
        titles = search_data[1] if len(search_data) > 1 else []
        if not titles:
            return {}

        title = titles[0]
        summary_response = requests.get(
            f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}",
            headers=headers,
            timeout=6,
        )
        summary_response.raise_for_status()
        summary = summary_response.json()
    except (requests.RequestException, ValueError, IndexError, TypeError):
        return {}

    extract = (summary.get("extract") or "").strip()
    source_url = summary.get("content_urls", {}).get("desktop", {}).get("page") or ""
    if not extract:
        return {}
    return {
        "title": summary.get("title") or title,
        "extract": extract,
        "source_url": source_url,
        "source_name": FREE_WEB_GENERAL_SOURCES["wikipedia"]["name"],
        "license": FREE_WEB_GENERAL_SOURCES["wikipedia"]["license"],
    }


def _wikidata_facts(question):
    if not _free_web_answers_enabled() or not _is_general_web_question(question):
        return {}
    query = _clean_general_web_query(question)
    lang = _wikipedia_language(question)
    try:
        response = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": query,
                "language": lang if lang in ("ar", "en", "ur") else "en",
                "uselang": lang if lang in ("ar", "en", "ur") else "en",
                "format": "json",
                "limit": 1,
            },
            headers={"User-Agent": "AccountingSystemAI/1.0 (free-commercial-source: Wikidata CC0)"},
            timeout=6,
        )
        response.raise_for_status()
        rows = response.json().get("search", [])
    except (requests.RequestException, ValueError, TypeError):
        return {}
    if not rows:
        return {}
    row = rows[0]
    return {
        "title": row.get("label") or query,
        "extract": row.get("description") or "",
        "source_url": row.get("concepturi") or row.get("url") or "",
        "source_name": FREE_WEB_GENERAL_SOURCES["wikidata"]["name"],
        "license": FREE_WEB_GENERAL_SOURCES["wikidata"]["license"],
    }


def _openalex_research(question):
    if not _free_web_answers_enabled() or not _is_general_web_question(question):
        return []
    query = _clean_general_web_query(question)
    try:
        response = requests.get(
            "https://api.openalex.org/works",
            params={
                "search": query,
                "per-page": 3,
                "sort": "cited_by_count:desc",
                "select": "id,display_name,publication_year,cited_by_count,primary_location,open_access",
            },
            headers={"User-Agent": "AccountingSystemAI/1.0 (free-commercial-source: OpenAlex CC0)"},
            timeout=7,
        )
        response.raise_for_status()
        rows = response.json().get("results", [])
    except (requests.RequestException, ValueError, TypeError):
        return []
    results = []
    for row in rows:
        title = (row.get("display_name") or "").strip()
        if not title:
            continue
        location = row.get("primary_location") or {}
        source = location.get("landing_page_url") or row.get("id") or ""
        results.append({
            "title": title,
            "extract": f"بحث/مرجع منشور سنة {row.get('publication_year') or 'غير محددة'}، وعدد الاستشهادات في OpenAlex: {row.get('cited_by_count') or 0}.",
            "source_url": source,
            "source_name": FREE_WEB_GENERAL_SOURCES["openalex"]["name"],
            "license": FREE_WEB_GENERAL_SOURCES["openalex"]["license"],
        })
    return results


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._in_title = False
        self._in_snippet = False
        self._current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._current = {"title": "", "url": attrs.get("href", ""), "snippet": ""}
            self._in_title = True
        elif self._current is not None and tag in {"a", "div"} and "result__snippet" in classes:
            self._in_snippet = True

    def handle_data(self, data):
        if not self._current:
            return
        text = unescape(data or "").strip()
        if not text:
            return
        if self._in_title:
            self._current["title"] = f"{self._current['title']} {text}".strip()
        elif self._in_snippet:
            self._current["snippet"] = f"{self._current['snippet']} {text}".strip()

    def handle_endtag(self, tag):
        if tag == "a" and self._in_title:
            self._in_title = False
        if self._in_snippet and tag in {"a", "div"}:
            self._in_snippet = False
            if self._current and self._current.get("title") and self._current.get("url"):
                self.results.append(self._current)
            self._current = None


def _clean_search_result_url(url):
    url = unescape(url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and "uddg=" in parsed.query:
        match = re.search(r"(?:^|&)uddg=([^&]+)", parsed.query)
        if match:
            from urllib.parse import unquote
            return unquote(match.group(1))
    return url


def _duckduckgo_web_search(question):
    if not _free_web_answers_enabled() or not _is_general_web_question(question):
        return []
    query = _clean_general_web_query(question)
    try:
        response = requests.get(
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            headers={
                "User-Agent": "Mozilla/5.0 AccountingSystemAI/1.0 (+https://example.com)",
                "Accept-Language": "ar,en;q=0.8",
            },
            timeout=8,
        )
        response.raise_for_status()
    except requests.RequestException:
        return []
    parser = _DuckDuckGoHTMLParser()
    parser.feed(response.text)
    results = []
    for row in parser.results[:5]:
        url = _clean_search_result_url(row.get("url"))
        title = re.sub(r"\s+", " ", row.get("title") or "").strip()
        snippet = re.sub(r"\s+", " ", row.get("snippet") or "").strip()
        if not title or not url:
            continue
        results.append({
            "title": title,
            "extract": snippet or "نتيجة ويب مرتبطة بالسؤال. افتح المصدر للتحقق من التفاصيل الكاملة.",
            "source_url": url,
            "source_name": FREE_WEB_GENERAL_SOURCES["duckduckgo"]["name"],
            "license": FREE_WEB_GENERAL_SOURCES["duckduckgo"]["license"],
        })
    return results


def _synthesize_free_web_answer(question, sources):
    if not sources:
        return ""
    current_warning = _question_needs_current_source_warning(question)
    ranked_sources = sorted(
        sources,
        key=lambda source: _source_reliability_score(source),
        reverse=True,
    )
    geography_question = _is_geography_question(question)
    if geography_question:
        ranked_sources.sort(
            key=lambda source: (
                source.get("kind") == "geography",
                "wikipedia" in (source.get("source_name") or "").lower(),
                _source_reliability_score(source),
            ),
            reverse=True,
        )
    primary = ranked_sources[0]
    answer_lines = [
        "الخلاصة:",
    ]
    if primary.get("extract"):
        answer_lines.append(f"- {primary['extract']}")
    else:
        answer_lines.append("- المعلومة المتاحة محدودة، لذلك الأفضل تضييق السؤال أو الرجوع لجهة رسمية متخصصة.")
    if geography_question and len(ranked_sources) > 1:
        useful_facts = []
        for source in ranked_sources[1:4]:
            extract = (source.get("extract") or "").strip()
            if extract and extract != primary.get("extract"):
                useful_facts.append(extract)
        if useful_facts:
            answer_lines.extend(["", "معلومات جغرافية مكملة:"])
            answer_lines.extend(f"- {fact}" for fact in useful_facts)
    elif len(ranked_sources) > 1:
        answer_lines.extend(["", "توضيح مهني:", "- تمت موازنة أكثر من نتيجة مرتبطة بالسؤال لتقليل الاعتماد على خلاصة منفردة أو غير مكتملة."])
        if any((source.get("source_name") or "").lower() == "openalex" for source in ranked_sources):
            answer_lines.append("- توجد إشارات بحثية أو أكاديمية مرتبطة بالموضوع؛ عند قرار مهم اقرأ المرجع الأصلي أو المصدر الرسمي.")
        answer_lines.append("- نقاط داعمة مختصرة:")
        for source in ranked_sources[1:4]:
            title = source.get("title") or source.get("source_name")
            extract = source.get("extract") or ""
            score = _source_reliability_score(source)
            answer_lines.append(f"  - {title}: {extract} درجة الاعتماد: {_source_reliability_label(score)}.")
    answer_lines.append("")
    if current_warning:
        answer_lines.append("تنبيه مهني: الموضوع يبدو حديثا أو سريع التغير؛ اعتمد على الجهة الرسمية الأحدث قبل اتخاذ قرار.")
    else:
        answer_lines.append("تنبيه مهني: هذه خلاصة مساعدة وليست بديلا عن المرجع الرسمي عند القرارات الحساسة.")

    references = []
    for source in ranked_sources[:3]:
        url = source.get("source_url") or ""
        title = source.get("title") or source.get("source_name") or ""
        if url and url.startswith("http"):
            references.append(f"{title}: {url}")
    if references:
        answer_lines.append("")
        answer_lines.append("مراجع مختصرة للتحقق:")
        answer_lines.extend(f"- {item}" for item in references)
    return "\n".join(answer_lines).strip()


def free_web_general_answer(question):
    normalized_question = normalize_user_question_text(question or "").strip().lower()
    cache_key = "ai_free_web_answer:" + hashlib.sha256(normalized_question.encode("utf-8")).hexdigest()
    cached_answer = cache.get(cache_key)
    if cached_answer:
        return cached_answer

    sources = []
    search_jobs = [
        ("duckduckgo", _duckduckgo_web_search),
        ("wikipedia", _wikipedia_summary),
        ("wikidata", _wikidata_facts),
        ("openalex", _openalex_research),
    ]
    if _is_geography_question(question):
        search_jobs.append(("nominatim", _nominatim_geography_facts))
    with ThreadPoolExecutor(max_workers=len(search_jobs)) as executor:
        futures = {executor.submit(func, question): name for name, func in search_jobs}
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception:
                continue
            if isinstance(result, list):
                sources.extend(result)
            elif result and result.get("extract"):
                sources.append(result)
    seen = set()
    unique_sources = []
    for source in sources:
        key = (source.get("source_name"), source.get("title"), source.get("source_url"))
        if key in seen:
            continue
        seen.add(key)
        unique_sources.append(source)
    answer = _synthesize_free_web_answer(question, unique_sources)
    if answer:
        cache.set(cache_key, answer, 60 * 10)
    return answer


def _weak_ai_answer(text):
    cleaned = (text or "").strip()
    if len(cleaned) < 35:
        return True
    weak_markers = (
        "لا أستطيع",
        "لا يمكنني",
        "غير متاح",
        "تعذر",
        "I cannot",
        "I can't",
        "as an ai",
        "how can I help",
        "please clarify",
        "need more information",
        "كيف يمكنني مساعدتك",
        "يرجى توضيح",
        "أحتاج المزيد",
        "لا توجد معلومات كافية",
        "ابتسامة",
        "نبرة",
        "كمساعد",
        "لا أملك سياق",
        "لا أملك معلومات كافية",
    )
    return any(marker.lower() in cleaned.lower() for marker in weak_markers)


CONFIRM_WORDS = ("تأكيد", "أكد", "اكيد", "أكيد", "اعتمد", "نفذ", "تمم", "احفظ", "yes", "confirm", "theek", "ٹھیک", "اوكي", "تمام")
CANCEL_WORDS = ("إلغاء", "الغاء", "لا", "تراجع", "cancel", "no")


def _is_confirm_text(text):
    normalized = _normalize_ai_text(text)
    return any(word.lower() in normalized for word in CONFIRM_WORDS)


def _is_cancel_text(text):
    normalized = _normalize_ai_text(text)
    return any(word.lower() in normalized for word in CANCEL_WORDS)


def _detect_pos_intent(text):
    normalized = _normalize_ai_text(text)
    explicit_pos_terms = (
        "كاشير", "نقطة بيع", "pos", "checkout", "تمم البيع", "خلص البيع",
        "داير ابيع", "عايز ابيع", "ابغى ابيع", "ابي ابيع", "bill banao",
    )
    if any(term in normalized for term in explicit_pos_terms):
        return True
    sale_terms = ("بيع", "بع", "فاتورة بيع", "فروخت", "بیع")
    has_sale_term = any(term in normalized for term in sale_terms)
    has_quantity = bool(re.search(r"\d+(?:[.,]\d+)?", normalized))
    explanation_terms = ("اشرح", "ما هو", "ما هي", "ما معنى", "كيف", "لماذا", "عرف", "تعريف")
    if any(term in normalized for term in explanation_terms):
        return False
    return has_sale_term and has_quantity


def _extract_requested_quantity(text, item_name):
    escaped = re.escape(item_name)
    patterns = (
        rf"(\d+(?:[.,]\d+)?)\s+(?:من\s+)?{escaped}",
        rf"{escaped}\s+(\d+(?:[.,]\d+)?)",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            return Decimal(match.group(1).replace(",", "."))
    return Decimal("1")


def _build_pos_sale_draft(branch_id, text, user=None):
    if not _detect_pos_intent(text):
        return None
    if not _user_can_read_context(user, "add_invoice", branch_id):
        return {
            "ok": True,
            "source": "ai_pos",
            "answer": "لا أستطيع تجهيز عملية كاشير لأن حسابك لا يملك صلاحية إضافة فواتير بيع.",
            "pending": None,
        }

    items = list(Item.objects.filter(branch_id=branch_id, is_active=True).order_by("name"))
    matched = []
    normalized = _normalize_ai_text(text)
    for item in items:
        if item.name and item.name.lower() in normalized:
            quantity = _extract_requested_quantity(text, item.name)
            price = item.selling_price or item.cost or Decimal("0")
            matched.append({
                "id": item.id,
                "name": item.name,
                "quantity": str(quantity),
                "price": str(price),
                "stock": str(item.quantity),
            })

    if not matched:
        return {
            "ok": True,
            "source": "ai_pos",
            "answer": "فهمت أنك تريد عملية كاشير، لكن لم أجد أسماء منتجات واضحة ومطابقة للمخزون. قل مثلا: بيع 2 قلم و1 دفتر، أو صوّر الباركود/الفاتورة بوضوح.",
            "pending": None,
        }

    subtotal = sum(Decimal(row["quantity"]) * Decimal(row["price"]) for row in matched)
    tax = Tax.objects.filter(name__icontains="15").first() or Tax.objects.first()
    vat_rate = tax.rate if tax else Decimal("15.00")
    vat = subtotal * (vat_rate / Decimal("100"))
    total = subtotal + vat
    payment_method = "بطاقة" if any(word in normalized for word in ("بطاقة", "شبكة", "مدى", "card")) else "نقدي"
    summary = [
        "جهزت مسودة عملية كاشير ولم أحفظها بعد.",
        "البنود:",
        *[f"- {row['name']}: كمية {row['quantity']} × سعر {row['price']} = {_money(Decimal(row['quantity']) * Decimal(row['price']))}" for row in matched],
        f"الإجمالي قبل الضريبة: {_money(subtotal)}",
        f"الضريبة: {_money(vat)}",
        f"المستحق: {_money(total)}",
        f"طريقة الدفع: {payment_method}",
        "للحفظ والترحيل المحاسبي قل أو اكتب: تأكيد. ولإلغاء المسودة قل: إلغاء.",
    ]
    return {
        "ok": True,
        "source": "ai_pos",
        "answer": "\n".join(summary),
        "pending": {
            "type": "pos_checkout",
            "payment_method": payment_method,
            "lines": matched,
        },
    }


def _detect_quote_intent(text):
    normalized = _normalize_ai_text(text)
    return any(word in normalized for word in (
        "عرض سعر", "عرض اسعار", "عرض أسعار", "quotation", "quote", "price offer", "تسعيرة",
    ))


def _extract_customer_name_for_quote(text):
    patterns = (
        r"(?:للعميل|لعميل|لشركة|للشركة)\s+([^\n،,]+)",
        r"(?:customer|client)\s+([A-Za-z0-9\u0600-\u06FF\s]{2,60})",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            return match.group(1).strip()[:180]
    return "عميل عرض سعر"


def _build_quote_draft(branch_id, text, user=None):
    if not _detect_quote_intent(text):
        return None
    if not _user_can_read_context(user, "add_invoice", branch_id):
        return {
            "ok": True,
            "source": "ai_quote",
            "answer": "لا أستطيع تجهيز عرض سعر لأن حسابك لا يملك صلاحية إضافة مستندات البيع.",
            "pending": None,
        }

    items = list(Item.objects.filter(branch_id=branch_id, is_active=True).order_by("name"))
    normalized = _normalize_ai_text(text)
    matched = []
    for item in items:
        if item.name and item.name.lower() in normalized:
            quantity = _extract_requested_quantity(text, item.name)
            price = item.selling_price or item.cost or Decimal("0")
            line_total = quantity * price
            vat = line_total * Decimal("0.15")
            matched.append({
                "id": item.id,
                "name": item.name,
                "description": item.name,
                "quantity": str(quantity),
                "price": str(price),
                "tax_rate": "15.00",
                "line_total": str(line_total),
                "line_vat": str(vat),
                "line_total_with_vat": str(line_total + vat),
            })
    if not matched:
        return {
            "ok": True,
            "source": "ai_quote",
            "answer": "فهمت أنك تريد عرض سعر، لكن لم أجد أصنافا واضحة مطابقة للمخزون. قل مثلا: أنشئ عرض سعر للعميل أحمد 2 Item.",
            "pending": None,
        }
    subtotal = sum(Decimal(row["line_total"]) for row in matched)
    vat_total = sum(Decimal(row["line_vat"]) for row in matched)
    total = subtotal + vat_total
    customer_name = _extract_customer_name_for_quote(text)
    summary = [
        "جهزت مسودة عرض سعر ولم أحفظها بعد.",
        f"العميل: {customer_name}",
        "البنود:",
        *[f"- {row['name']}: كمية {row['quantity']} × سعر {row['price']} = {_money(Decimal(row['line_total_with_vat']))}" for row in matched],
        f"الإجمالي قبل الضريبة: {_money(subtotal)}",
        f"الضريبة: {_money(vat_total)}",
        f"الإجمالي شامل الضريبة: {_money(total)}",
        "للمتابعة قل أو اكتب: تأكيد. وللتراجع قل: إلغاء.",
    ]
    return {
        "ok": True,
        "source": "ai_quote",
        "answer": "\n".join(summary),
        "pending": {
            "type": "quote_create",
            "customer_name": customer_name,
            "lines": matched,
            "notes": "تم إنشاؤه بواسطة الذكاء الاصطناعي بعد موافقة المستخدم.",
        },
    }


def _execute_quote_create(branch_id, draft, user=None):
    if not _user_can_read_context(user, "add_invoice", branch_id):
        return {"ok": True, "source": "ai_quote", "answer": "لا أستطيع حفظ عرض السعر لأن حسابك لا يملك الصلاحية المطلوبة.", "pending": None}
    branch = Branch.objects.select_related("company").get(id=branch_id)
    customer, _ = Customer.objects.get_or_create(name=draft.get("customer_name") or "عميل عرض سعر", defaults={"country": "SA"})
    quote_number = f"Q-AI-{timezone.now().strftime('%Y%m%d%H%M%S')}-{Quote.objects.count() + 1}"
    with transaction.atomic():
        quote = Quote.objects.create(
            branch=branch,
            customer=customer,
            quote_number=quote_number,
            valid_until=timezone.localdate() + timezone.timedelta(days=15),
            notes=draft.get("notes", ""),
        )
        subtotal = Decimal("0.00")
        vat_total = Decimal("0.00")
        total = Decimal("0.00")
        for row in draft.get("lines") or []:
            item = Item.objects.filter(id=row.get("id"), branch=branch).first()
            quantity = Decimal(str(row.get("quantity") or "0"))
            unit_price = Decimal(str(row.get("price") or "0"))
            tax_rate = Decimal(str(row.get("tax_rate") or "15"))
            line_total = quantity * unit_price
            line_vat = line_total * (tax_rate / Decimal("100"))
            line_total_with_vat = line_total + line_vat
            QuoteItem.objects.create(
                branch=branch,
                quote=quote,
                item=item,
                description=row.get("description") or row.get("name") or "بند عرض سعر",
                quantity=quantity,
                unit_price=unit_price,
                tax_rate=tax_rate,
                line_total=line_total,
                line_vat=line_vat,
                line_total_with_vat=line_total_with_vat,
            )
            subtotal += line_total
            vat_total += line_vat
            total += line_total_with_vat
        quote.total_amount = subtotal
        quote.total_vat = vat_total
        quote.total_with_vat = total
        quote.save(update_fields=["total_amount", "total_vat", "total_with_vat"])
    return {
        "ok": True,
        "source": "ai_quote",
        "answer": f"تم حفظ عرض السعر {quote.quote_number} بإجمالي {_money(quote.total_with_vat)}. يمكنك تنزيله PDF من صفحة عرض السعر. هذا المستند لا يؤثر محاسبيا حتى يتم تحويله إلى فاتورة.",
        "pending": None,
        "action": {"type": "navigate", "title": "عرض وتنزيل PDF", "url": f"/invoicing/quotes/{quote.id}/", "auto_open": False},
    }


def _execute_pos_sale(branch_id, draft, user=None):
    if not _user_can_read_context(user, "add_invoice", branch_id):
        return {"ok": True, "source": "ai_pos", "answer": "لا أستطيع حفظ عملية الكاشير لأن حسابك لا يملك صلاحية إضافة فواتير بيع.", "pending": None}
    lines = draft.get("lines") or []
    if not lines:
        return {"ok": True, "source": "ai_pos", "answer": "لا توجد بنود في مسودة الكاشير.", "pending": None}

    from core.models import Branch
    from .views import post_sales_invoice
    branch = Branch.objects.select_related("company").get(id=branch_id)
    customer, _ = Customer.objects.get_or_create(name="عميل نقدي", defaults={"country": "SA"})
    tax, _ = Tax.objects.get_or_create(name="VAT 15%", defaults={"rate": Decimal("15.00")})
    invoice_number = f"AI-POS-{timezone.now().strftime('%Y%m%d%H%M%S')}-{Invoice.objects.count() + 1}"
    payment_method = draft.get("payment_method") or "نقدي"

    with transaction.atomic():
        from core.services.monthly_close import assert_month_open
        assert_month_open(branch.company, timezone.localdate())
        invoice = Invoice.objects.create(
            branch=branch,
            invoice_number=invoice_number,
            invoice_type="simplified",
            customer=customer,
            payment_method=payment_method,
        )
        total_amount = Decimal("0.00")
        total_vat = Decimal("0.00")
        total_with_vat = Decimal("0.00")
        for row in lines:
            item = Item.objects.select_for_update().get(id=row.get("id"), branch=branch)
            quantity = Decimal(str(row.get("quantity") or "0"))
            unit_price = Decimal(str(row.get("price") or item.selling_price or item.cost or "0"))
            if quantity <= 0:
                raise ValueError("الكمية يجب أن تكون أكبر من صفر.")
            if item.quantity < quantity:
                raise ValueError(f"المخزون غير كاف للصنف {item.name}.")
            line_total = quantity * unit_price
            line_vat = line_total * (tax.rate / Decimal("100"))
            line_total_with_vat = line_total + line_vat
            InvoiceItem.objects.create(
                branch=branch,
                invoice=invoice,
                item=item,
                description=item.name,
                quantity=quantity,
                unit_price=unit_price,
                tax=tax,
                line_total=line_total,
                line_vat=line_vat,
                line_total_with_vat=line_total_with_vat,
            )
            total_amount += line_total
            total_vat += line_vat
            total_with_vat += line_total_with_vat
        invoice.total_amount = total_amount
        invoice.total_vat = total_vat
        invoice.total_with_vat = total_with_vat
        invoice.save(update_fields=["total_amount", "total_vat", "total_with_vat"])
        zatca_payload = prepare_zatca_payload(invoice)
        post_sales_invoice(invoice)
        invoice.is_posted = True
        if zatca_payload["warnings"]:
            invoice.zatca_warnings = "\n".join(str(warning) for warning in zatca_payload["warnings"])
            invoice.zatca_status = "غير مستوفية"
            invoice.save(update_fields=["is_posted", "zatca_warnings", "zatca_status", "journal_entry"])
        else:
            invoice.zatca_qr = zatca_payload["qr"]
            invoice.zatca_xml = zatca_payload["xml"]
            invoice.zatca_hash = zatca_payload["hash"]
            invoice.zatca_status = "جاهزة للإرسال"
            invoice.save(update_fields=["is_posted", "zatca_qr", "zatca_xml", "zatca_hash", "zatca_status", "journal_entry"])

    return {
        "ok": True,
        "source": "ai_pos",
        "answer": f"تم حفظ عملية الكاشير وإصدار فاتورة {invoice.invoice_number} بإجمالي {_money(invoice.total_with_vat)}. تم ربطها محاسبيا بالقيد رقم {invoice.journal_entry_id or 'غير مرحل بسبب تنبيهات الفوترة'} وحالة الفوترة: {invoice.zatca_status}.",
        "pending": None,
        "action": {"type": "navigate", "title": "عرض الفاتورة", "url": f"/invoicing/{invoice.id}/", "auto_open": False},
    }


def generate_financial_insights(branch_id, user=None):
    context = branch_ai_context(branch_id, user=user)
    fallback = local_financial_insights(context)
    prompt = _professional_prompt(
        "financial_insights",
        "حلل بيانات الفرع وقدم 5 توصيات عملية قصيرة.",
        context,
        "ركز على الأولويات: السيولة، المبيعات، المشتريات، المخزون، والعمليات غير المكتملة. لا تخترع أرقاما.",
    )
    result = _private_ai_request(prompt, max_new_tokens=1100, task="financial_insights", context=context)
    if not result.get("ok") or _weak_ai_answer(result.get("text")):
        return {
            "ok": True,
            "source": "local",
            "context": context,
            "tips": fallback,
            "warning": result.get("message"),
        }

    tips = [line.strip(" -•\t") for line in result["text"].splitlines() if line.strip()]
    return {"ok": True, "source": "private", "context": context, "tips": tips[:7] or fallback}


def _model_answer_financial_question(branch_id, question, user=None):
    context = branch_ai_context(branch_id, user=user)
    restricted_message = _restricted_context_message(context)
    if _question_requests_restricted_data(question, context):
        return {
            "ok": True,
            "source": "permissions",
            "answer": restricted_message or "أعتذر، لا أستطيع عرض هذه المعلومة لأن حسابك لا يملك صلاحية الوصول إليها.",
            "context": {"restricted_sections": context.get("restricted_sections", [])},
        }
    precise_answer = _answer_precise_accounting_question(branch_id, question, user=user)
    if precise_answer:
        return {
            "ok": True,
            "source": "accounting_data",
            "answer": precise_answer,
            "context": context,
        }
    usage_answer = local_system_usage_answer(question)
    prompt = _professional_prompt(
        "financial_question",
        question,
        context,
        "أجب بصيغة عملية: فهم السؤال، الإجابة، مفهوم محاسبي عند الحاجة، والخطوة التالية داخل النظام.",
    )
    result = _private_ai_request(prompt, max_new_tokens=1200, task="financial_question", context=context)
    if not result.get("ok") or _weak_ai_answer(result.get("text")):
        fallback_answer = strong_local_financial_answer(context, question, restricted_message)
        return {
            "ok": True,
            "source": "local_strong",
            "answer": fallback_answer,
            "context": context,
            "warning": result.get("message"),
        }

    answer = result["text"]
    if restricted_message:
        answer = f"{restricted_message}\n\n{answer}"
    return {"ok": True, "source": "private", "answer": answer, "context": context}

def answer_financial_question(branch_id, question, user=None):
    def finish(result):
        finalized = _finalize_ai_result(result, question)
        if "question_analysis" not in finalized:
            finalized["question_analysis"] = question_analysis
        return finalized

    question = normalize_user_question_text(question)
    question_analysis = _analyze_user_question(question)
    policy_answer = islamic_policy_guard_answer(question)
    if policy_answer:
        return finish({
            "ok": True,
            "source": "islamic_policy",
            "answer": _polish_answer(policy_answer, question),
            "context": {},
        })
    calculation_answer = local_calculation_answer(question)
    if calculation_answer:
        return finish({
            "ok": True,
            "source": "local_calculator",
            "answer": _polish_answer(calculation_answer, question),
            "context": {},
        })
    ambiguous_answer = local_ambiguous_request_answer(question)
    if ambiguous_answer:
        return finish({
            "ok": True,
            "source": "clarification",
            "answer": _polish_answer(ambiguous_answer, question),
            "context": {},
        })
    zatca_answer = zatca_regulations_answer(question)
    if zatca_answer:
        return finish({
            "ok": True,
            "source": "zatca_regulations",
            "answer": _polish_answer(zatca_answer, question),
            "context": {},
        })
    local_direct_answer = local_greeting_or_concept_answer(question)
    usage_answer = local_system_usage_answer(question)
    if local_direct_answer and _is_light_conversation_question(question):
        return finish({
            "ok": True,
            "source": "local",
            "answer": _polish_answer(local_direct_answer, question),
            "context": {},
        })
    if local_direct_answer and not question_analysis.get("asks_research") and not question_analysis.get("asks_company_data"):
        return finish({
            "ok": True,
            "source": "local",
            "answer": _polish_answer(local_direct_answer, question),
            "context": {},
        })
    if usage_answer and _is_system_usage_question(question):
        return finish({
            "ok": True,
            "source": "local",
            "answer": _polish_answer(usage_answer, question),
            "context": {},
        })
    knowledge_answer = local_knowledge_answer(question, user=user, branch_id=branch_id)
    if knowledge_answer:
        return finish({
            "ok": True,
            "source": "local_knowledge",
            "answer": _polish_answer(knowledge_answer, question),
            "context": {},
        })
    if _free_web_answers_enabled() and question_analysis.get("asks_research"):
        web_answer = free_web_general_answer(question)
        if web_answer:
            return finish({
                "ok": True,
                "source": "free_web",
                "answer": _polish_answer(web_answer, question),
                "context": {},
            })
    if local_direct_answer and question_analysis.get("needs_explanation"):
        return finish({
            "ok": True,
            "source": "local",
            "answer": _polish_answer(local_direct_answer, question),
            "context": {},
        })
    result = _model_answer_financial_question(branch_id, question, user=user)
    answer_text = result.get("answer") or result.get("message") or ""
    if _weak_ai_answer(answer_text) and result.get("source") not in {"permissions", "accounting_data"}:
        if _free_web_answers_enabled() and not _requests_accounting_data_or_analysis(question):
            web_answer = free_web_general_answer(question)
            if web_answer:
                return finish({
                    "ok": True,
                    "source": "free_web",
                    "answer": _polish_answer(web_answer, question),
                    "context": {},
                })
        context = result.get("context") or branch_ai_context(branch_id, user=user)
        if local_direct_answer and not _requests_accounting_data_or_analysis(question):
            result["answer"] = _polish_answer(local_direct_answer, question)
            result["source"] = "local"
            result["context"] = {}
        else:
            result["answer"] = _polish_answer(strong_local_financial_answer(context, question), question)
            result["source"] = "local_strong"
            result["context"] = context
        return finish(result)
    result["answer"] = _polish_answer(answer_text, question)
    return finish(result)


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
        "name": "quotes",
        "title": "عروض الأسعار",
        "url_name": "quote_list",
        "keywords": ("عروض الأسعار", "عروض سعر", "عرض سعر", "quotation", "quote"),
        "description": "فتح قائمة عروض الأسعار.",
    },
    {
        "name": "quote_create",
        "title": "إنشاء عرض سعر",
        "url_name": "quote_create",
        "keywords": ("إنشاء عرض سعر", "انشاء عرض سعر", "أضف عرض سعر", "اضف عرض سعر", "عرض سعر جديد"),
        "description": "فتح نموذج إنشاء عرض سعر.",
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


ASSISTANT_ACTION_PERMISSIONS = {
    "invoice_list": "view_invoice",
    "invoice_create": "add_invoice",
    "quote_list": "view_invoice",
    "quote_create": "add_invoice",
    "pos_terminal": "add_invoice",
    "purchase_list": "view_purchaseinvoice",
    "purchase_add": "add_purchaseinvoice",
    "inventory_list": "view_item",
    "customer_list": "view_customer",
    "supplier_list": "view_supplier",
    "journal_list": "view_journalentry",
    "journal_add": "add_journalentry",
    "payroll_report": "view_salaryrecord",
    "advance_report": "view_employeeadvance",
    "unposted_operations_report": "view_journalentry",
    "ai_invoice_import": "import_ai_invoice",
    "ai_insights": "view_ai_insights",
    "ai_assistant": "view_ai_insights",
}


def _assistant_action_allowed(user, action, branch_id):
    permission = ASSISTANT_ACTION_PERMISSIONS.get(action.get("url_name"))
    if not permission:
        return True
    return _user_can_read_context(user, permission, branch_id)


def _safe_reverse(url_name):
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return ""


def analyze_and_route_user_request(branch_id, request_text, pending=None, user=None):
    text = normalize_user_question_text(request_text)
    pending = pending or {}
    question_analysis = _analyze_user_question(text)
    def finish_route(result):
        result = _finalize_ai_result(result, text)
        result["question_analysis"] = question_analysis
        answer = result.get("answer") or ""
        if _answer_looks_irrelevant(text, answer):
            result["answer"] = _repair_irrelevant_answer(text, answer)
            result["source"] = "local_repaired"
            result["confidence"] = "medium"
            result["intent"] = _classify_question_intent(text)
        return result

    if pending.get("type") == "quote_create":
        if _is_cancel_text(text):
            return finish_route({
                "ok": True,
                "answer": "تم إلغاء مسودة عرض السعر. لم يتم حفظ أي شيء في النظام.",
                "source": "ai_quote",
                "pending": None,
                "action": {"type": "answer", "title": "", "url": "", "auto_open": False},
                "suggestions": [],
                "followups": ["إنشاء عرض سعر جديد", "افتح عروض الأسعار"],
                "context": {},
            })
        if _is_confirm_text(text):
            try:
                result = _execute_quote_create(branch_id, pending, user=user)
            except Exception as exc:
                result = {"ok": True, "source": "ai_quote", "answer": f"لم أحفظ عرض السعر بسبب مشكلة: {exc}", "pending": None}
            return finish_route({
                "ok": True,
                "answer": _polish_answer(result.get("answer", ""), text),
                "source": result.get("source", "ai_quote"),
                "pending": result.get("pending"),
                "action": result.get("action") or {"type": "answer", "title": "", "url": "", "auto_open": False},
                "suggestions": [],
                "followups": ["تنزيل PDF", "إنشاء عرض سعر جديد"],
                "context": {},
            })
        return finish_route({
            "ok": True,
            "answer": "مسودة عرض السعر بانتظار موافقتك. قل أو اكتب: تأكيد للحفظ، أو إلغاء للتراجع.",
            "source": "ai_quote",
            "pending": pending,
            "action": {"type": "answer", "title": "", "url": "", "auto_open": False},
            "suggestions": [],
            "followups": ["تأكيد", "إلغاء"],
            "context": {},
        })
    if pending.get("type") == "pos_checkout":
        if _is_cancel_text(text):
            return finish_route({
                "ok": True,
                "answer": "تم إلغاء مسودة الكاشير. لم يتم حفظ أي شيء في النظام.",
                "source": "ai_pos",
                "pending": None,
                "action": {"type": "answer", "title": "", "url": "", "auto_open": False},
                "suggestions": [],
                "followups": ["ابدأ عملية كاشير جديدة", "حلل مبيعات هذا الشهر"],
                "context": {},
            })
        if _is_confirm_text(text):
            try:
                result = _execute_pos_sale(branch_id, pending, user=user)
            except Exception as exc:
                result = {"ok": True, "source": "ai_pos", "answer": f"لم أحفظ العملية بسبب مشكلة: {exc}", "pending": None}
            return finish_route({
                "ok": True,
                "answer": _polish_answer(result.get("answer", ""), text),
                "source": result.get("source", "ai_pos"),
                "pending": result.get("pending"),
                "action": result.get("action") or {"type": "answer", "title": "", "url": "", "auto_open": False},
                "suggestions": [],
                "followups": _quality_followups(text),
                "context": {},
            })
        return finish_route({
            "ok": True,
            "answer": "لا تزال مسودة الكاشير بانتظار موافقتك. قل أو اكتب: تأكيد للحفظ والترحيل، أو إلغاء للتراجع.",
            "source": "ai_pos",
            "pending": pending,
            "action": {"type": "answer", "title": "", "url": "", "auto_open": False},
            "suggestions": [],
            "followups": ["تأكيد", "إلغاء"],
            "context": {},
        })

    should_try_execution = _should_try_execution(question_analysis)

    quote_draft = _build_quote_draft(branch_id, text, user=user) if should_try_execution else None
    if quote_draft:
        return finish_route({
            "ok": True,
            "answer": _polish_answer(quote_draft.get("answer", ""), text),
            "source": quote_draft.get("source", "ai_quote"),
            "pending": quote_draft.get("pending"),
            "action": {"type": "answer", "title": "", "url": "", "auto_open": False},
            "suggestions": [],
            "followups": ["تأكيد", "إلغاء"] if quote_draft.get("pending") else _quality_followups(text),
            "context": {},
        })

    pos_draft = _build_pos_sale_draft(branch_id, text, user=user) if should_try_execution else None
    if pos_draft:
        return finish_route({
            "ok": True,
            "answer": _polish_answer(pos_draft.get("answer", ""), text),
            "source": pos_draft.get("source", "ai_pos"),
            "pending": pos_draft.get("pending"),
            "action": {"type": "answer", "title": "", "url": "", "auto_open": False},
            "suggestions": [],
            "followups": ["تأكيد", "إلغاء"] if pos_draft.get("pending") else _quality_followups(text),
            "context": {},
        })

    management_result = handle_ai_management_command(branch_id, text, pending=pending, user=user) if should_try_execution else None
    if management_result:
        answer = _polish_answer(management_result.get("answer", ""), text)
        return finish_route({
            "ok": True,
            "answer": answer,
            "source": management_result.get("source", "ai_actions"),
            "pending": management_result.get("pending"),
            "action": {"type": "answer", "title": "", "url": "", "auto_open": False},
            "suggestions": [],
            "followups": _quality_followups(text),
            "context": {},
        })

    normalized = text.lower()
    matched = []
    denied_actions = []
    for action in ASSISTANT_ACTIONS:
        score = sum(len(keyword) for keyword in action["keywords"] if keyword.lower() in normalized)
        if score:
            if not _assistant_action_allowed(user, action, branch_id):
                denied_actions.append(action)
                continue
            url = _safe_reverse(action["url_name"])
            if url:
                matched.append({**action, "score": score, "url": url})

    matched.sort(key=lambda row: row["score"], reverse=True)
    primary = matched[0] if matched else None
    wants_open = any(word in normalized for word in ("افتح", "اذهب", "روح", "انتقل", "اعرض", "أظهر", "نفذ", "ابدأ"))
    wants_create = any(word in normalized for word in ("أضف", "اضف", "أنشئ", "انشئ", "سجل", "ادخل"))
    wants_navigation = wants_open or wants_create
    navigation_primary = primary if wants_navigation else None

    financial_answer = answer_financial_question(branch_id, text, user=user)
    answer_text = financial_answer.get("answer") or financial_answer.get("message") or ""
    if denied_actions and not navigation_primary:
        title = denied_actions[0]["title"]
        answer_text = f"أعتذر بلطف، لا أستطيع فتح أو عرض {title} لأن حسابك لا يملك الصلاحية المطلوبة. يمكنك طلب الصلاحية من مدير النظام.\n\n{answer_text}".strip()

    if navigation_primary:
        action_text = f"فهمت طلبك: {navigation_primary['description']}"
        if wants_create:
            action_text += " يمكنك إدخال البيانات من النموذج ثم الحفظ."
        elif wants_open:
            action_text += " سأفتح الصفحة المناسبة."
        answer_text = f"{action_text}\n\n{answer_text}".strip()

    answer_text = _polish_answer(answer_text, text, navigation_primary)

    return finish_route({
        "ok": True,
        "answer": answer_text,
        "source": financial_answer.get("source", "local"),
        "action": {
            "type": "navigate" if navigation_primary else "answer",
            "title": navigation_primary["title"] if navigation_primary else "",
            "url": navigation_primary["url"] if navigation_primary else "",
            "auto_open": bool(navigation_primary and wants_open),
        },
        "suggestions": [
            {"title": row["title"], "url": row["url"], "description": row["description"]}
            for row in matched[:4]
        ],
        "followups": _quality_followups(text, primary),
        "context": financial_answer.get("context", {}),
    })


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
