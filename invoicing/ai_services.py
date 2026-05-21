import base64
import json
import os
import re
from decimal import Decimal

import requests
from django.conf import settings
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
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
    max_new_tokens = min(int(max_new_tokens or 220), 300)
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


def generate_financial_insights(branch_id):
    context = branch_ai_context(branch_id)
    fallback = local_financial_insights(context)
    prompt = (
        "أنت نموذج عبدالرحمن المحاسبي داخل نظام محاسبي سعودي. "
        "حلل بيانات الفرع التالية بالعربية وقدم 5 توصيات عملية قصيرة دون اختراع أرقام غير موجودة:\n"
        f"{json.dumps(context, ensure_ascii=False, default=str)}"
    )
    result = _private_ai_request(prompt, max_new_tokens=300, task="financial_insights", context=context)
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
    prompt = (
        "أجب بالعربية كمساعد مالي خاص داخل نظام محاسبي. استخدم بيانات الفرع المتاحة فقط، "
        "وإذا لم تكف البيانات فاذكر ذلك بوضوح. لا تقدم استشارة قانونية نهائية.\n"
        f"بيانات الفرع: {json.dumps(context, ensure_ascii=False, default=str)}\n"
        f"سؤال المستخدم: {question}"
    )
    result = _private_ai_request(prompt, max_new_tokens=300, task="financial_question", context=context)
    if not result.get("ok") or not result.get("text"):
        return {
            "ok": True,
            "source": "local",
            "answer": "تعذر الاتصال بالنموذج الخاص حاليا. بناء على البيانات الحالية: " + " ".join(local_financial_insights(context)),
            "context": context,
            "warning": result.get("message"),
        }

    return {"ok": True, "source": "private", "answer": result["text"], "context": context}


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
