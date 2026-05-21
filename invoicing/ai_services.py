import base64
import json
import os
import re
from decimal import Decimal

import requests
from django.conf import settings
from django.db.models import Count, F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Invoice, InvoiceItem, Item, PurchaseInvoice

API_KEY_ENV_NAMES = ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GEMINI_API_KEY")


def _google_api_key():
    for name in API_KEY_ENV_NAMES:
        value = getattr(settings, name, "") or os.environ.get(name, "")
        value = str(value or "").strip().strip('"').strip("'")
        if value:
            return value
    return ""


def _gemini_model():
    return (getattr(settings, "GEMINI_INVOICE_MODEL", "") or os.environ.get("GEMINI_INVOICE_MODEL", "gemini-2.0-flash")).strip()


def ai_configuration_status():
    configured_name = ""
    for name in API_KEY_ENV_NAMES:
        value = getattr(settings, name, "") or os.environ.get(name, "")
        if str(value or "").strip().strip('"').strip("'"):
            configured_name = name
            break
    return {
        "has_key": bool(configured_name),
        "key_name": configured_name,
        "model": _gemini_model(),
        "accepted_names": API_KEY_ENV_NAMES,
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


def _gemini_generate_text(prompt, temperature=0.25):
    key = _google_api_key()
    if not key:
        return {
            "ok": False,
            "message": "لم يتم العثور على مفتاح Gemini. أضف GOOGLE_API_KEY أو GEMINI_API_KEY في متغيرات البيئة ثم أعد نشر الخدمة.",
        }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{_gemini_model()}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    try:
        response = requests.post(url, params={"key": key}, json=payload, timeout=60)
    except requests.RequestException as exc:
        return {"ok": False, "message": "تعذر الاتصال بخدمة Gemini.", "raw": str(exc)[:1000]}
    if response.status_code >= 400:
        return {
            "ok": False,
            "message": f"تعذر الاتصال بخدمة Gemini: {response.status_code}",
            "raw": response.text[:1000],
        }
    text = ""
    for candidate in response.json().get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text += part.get("text", "")
    return {"ok": True, "text": text.strip()}


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
        tips.append(f"يوجد {context['low_stock_count']} صنفاً عند حد التنبيه أو أقل، وأهمها: {', '.join(context['low_stock_items'])}.")
    if context["invoice_count"] and not context["customers_count"]:
        tips.append("توجد فواتير بدون تنوع واضح في العملاء؛ راجع بيانات العملاء وربطها بالفواتير.")
    if not tips:
        tips.append("المؤشرات الأساسية مستقرة حالياً. تابع التدفق النقدي والمخزون بشكل أسبوعي.")
    return tips


def generate_financial_insights(branch_id):
    context = branch_ai_context(branch_id)
    fallback = local_financial_insights(context)
    if not _google_api_key():
        return {"ok": True, "source": "local", "context": context, "tips": fallback}
    prompt = (
        "أنت مستشار مالي ومحاسبي لنظام سعودي. حلل هذه البيانات المختصرة بالعربية، "
        "وقدّم 5 توصيات عملية قصيرة بدون مبالغة وبدون اختراع أرقام غير موجودة:\n"
        f"{json.dumps(context, ensure_ascii=False, default=str)}"
    )
    result = _gemini_generate_text(prompt)
    if not result.get("ok"):
        return {"ok": True, "source": "local", "context": context, "tips": fallback, "warning": result.get("message")}
    tips = [line.strip(" -•\t") for line in result["text"].splitlines() if line.strip()]
    return {"ok": True, "source": "gemini", "context": context, "tips": tips[:7] or fallback}


def answer_financial_question(branch_id, question):
    context = branch_ai_context(branch_id)
    if not _google_api_key():
        return {
            "ok": True,
            "source": "local",
            "answer": "لم يتم ضبط مفتاح Gemini بعد. بناءً على البيانات الحالية: " + " ".join(local_financial_insights(context)),
            "context": context,
        }
    prompt = (
        "أجب بالعربية كمساعد مالي داخل نظام محاسبي. استخدم البيانات المتاحة فقط، "
        "وإذا لم تكف البيانات فاذكر ذلك بوضوح. لا تقدم استشارة قانونية نهائية.\n"
        f"بيانات الفرع: {json.dumps(context, ensure_ascii=False, default=str)}\n"
        f"سؤال المستخدم: {question}"
    )
    result = _gemini_generate_text(prompt)
    if not result.get("ok"):
        return {"ok": False, "message": result.get("message"), "raw": result.get("raw", "")}
    return {"ok": True, "source": "gemini", "answer": result["text"], "context": context}


def extract_invoice_from_image(uploaded_file):
    key = _google_api_key()
    if not key:
        return {
            "ok": False,
            "message": "لم يتم العثور على مفتاح Gemini. أضف GOOGLE_API_KEY أو GEMINI_API_KEY في متغيرات البيئة ثم أعد نشر الخدمة.",
        }

    content = uploaded_file.read()
    image_b64 = base64.b64encode(content).decode("utf-8")
    media_type = uploaded_file.content_type or "image/jpeg"
    prompt = (
        "استخرج بيانات فاتورة شراء من الصورة. أعد JSON فقط دون شرح بالمفاتيح التالية: "
        "supplier_name, invoice_number, issue_date بصيغة YYYY-MM-DD, subtotal, vat, total, "
        "items كقائمة عناصر، وكل عنصر يحتوي name, quantity, unit_price. "
        "استخدم الأرقام فقط للقيم المالية والكميات."
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{_gemini_model()}:generateContent"
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": media_type, "data": image_b64}},
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json",
        },
    }
    try:
        response = requests.post(url, params={"key": key}, json=payload, timeout=60)
    except requests.RequestException as exc:
        return {
            "ok": False,
            "message": "تعذر الاتصال بخدمة Gemini. تحقق من اتصال الخادم ومن صحة إعدادات المفتاح.",
            "raw": str(exc)[:1000],
        }
    if response.status_code >= 400:
        error_message = f"تعذر الاتصال بخدمة Gemini: {response.status_code}"
        if response.status_code in (400, 404):
            error_message += " - تحقق من اسم النموذج GEMINI_INVOICE_MODEL."
        elif response.status_code in (401, 403):
            error_message += " - تحقق من صحة المفتاح وتفعيل Gemini API."
        elif response.status_code == 429:
            error_message += " - تم تجاوز حد الاستخدام مؤقتاً."
        return {
            "ok": False,
            "message": error_message,
            "raw": response.text[:1000],
        }

    data = response.json()
    text = ""
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text += part.get("text", "")
    try:
        extracted = _json_from_text(text)
    except (json.JSONDecodeError, TypeError):
        return {"ok": False, "message": "تعذر قراءة نتيجة Gemini كبيانات منظمة.", "raw": text}
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
