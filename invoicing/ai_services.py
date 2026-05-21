import base64
import json
import os
import re
from decimal import Decimal

import requests
from django.conf import settings

from .models import Item

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
