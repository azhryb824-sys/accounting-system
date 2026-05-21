import base64
import json
import os
import re
from decimal import Decimal

import requests
from django.conf import settings

from .models import Item


def _google_api_key():
    return getattr(settings, "GOOGLE_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")


def _gemini_model():
    return getattr(settings, "GEMINI_INVOICE_MODEL", "") or os.environ.get("GEMINI_INVOICE_MODEL", "gemini-1.5-flash")


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
            "message": "لم يتم ضبط GOOGLE_API_KEY بعد. أضفه كمتغير بيئة ثم أعد تشغيل الخادم.",
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
    response = requests.post(url, params={"key": key}, json=payload, timeout=60)
    if response.status_code >= 400:
        return {
            "ok": False,
            "message": f"تعذر الاتصال بخدمة Gemini: {response.status_code}",
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
