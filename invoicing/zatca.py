import base64
import hashlib
import re
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings

from .qr_generator import QRGenerator
from .xml_generator import XMLGenerator


VAT_RATE = Decimal("15.00")
VAT_NUMBER_RE = re.compile(r"^3\d{13}3$")


def _money(value):
    return Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _seller(invoice):
    company = invoice.branch.company
    return {
        "name": getattr(settings, "COMPANY_NAME", "") or company.name,
        "vat_number": str(getattr(settings, "COMPANY_VAT_NUMBER", "") or company.vat_number or "").strip(),
        "address": company.address or invoice.branch.address or "",
    }


def invoice_hash(xml_text):
    return hashlib.sha256(xml_text.encode("utf-8")).hexdigest()


def validate_invoice(invoice):
    warnings = []
    seller = _seller(invoice)

    if not seller["name"]:
        warnings.append("اسم البائع مطلوب في الفاتورة الإلكترونية.")
    if not VAT_NUMBER_RE.match(seller["vat_number"]):
        warnings.append("الرقم الضريبي للبائع يجب أن يكون 15 رقما ويبدأ بالرقم 3 وينتهي بالرقم 3.")
    if not seller["address"]:
        warnings.append("عنوان البائع مطلوب لإكمال بيانات الفاتورة.")
    if not invoice.invoice_number:
        warnings.append("رقم الفاتورة مطلوب.")
    if not invoice.uuid:
        warnings.append("معرف UUID للفاتورة مطلوب.")
    if not invoice.issue_date:
        warnings.append("تاريخ ووقت إصدار الفاتورة مطلوبان.")
    if invoice.total_with_vat <= Decimal("0"):
        warnings.append("إجمالي الفاتورة شامل الضريبة يجب أن يكون أكبر من صفر.")
    if not invoice.items.exists():
        warnings.append("الفاتورة يجب أن تحتوي على بند واحد على الأقل.")

    if invoice.invoice_type == "standard":
        customer_vat = str(invoice.customer.vat_number or "").strip()
        if not VAT_NUMBER_RE.match(customer_vat):
            warnings.append("الفاتورة الضريبية تتطلب رقما ضريبيا صحيحا للعميل.")

    calculated_subtotal = Decimal("0")
    calculated_vat = Decimal("0")
    for line in invoice.items.select_related("tax", "item"):
        if line.quantity <= 0:
            warnings.append(f"كمية البند ({line.description or line.item.name}) يجب أن تكون أكبر من صفر.")
        if line.unit_price < 0:
            warnings.append(f"سعر البند ({line.description or line.item.name}) لا يمكن أن يكون سالبا.")
        if line.tax.rate != VAT_RATE:
            warnings.append(f"نسبة الضريبة في البند ({line.description or line.item.name}) يجب أن تكون 15%.")
        calculated_subtotal += _money(line.quantity * line.unit_price)
        calculated_vat += _money(line.line_total * (line.tax.rate / Decimal("100")))

    calculated_total = calculated_subtotal + calculated_vat
    if _money(invoice.total_amount) != _money(calculated_subtotal):
        warnings.append("إجمالي الفاتورة قبل الضريبة لا يطابق مجموع البنود.")
    if _money(invoice.total_vat) != _money(calculated_vat):
        warnings.append("قيمة الضريبة لا تطابق ضريبة البنود المحسوبة.")
    if _money(invoice.total_with_vat) != _money(calculated_total):
        warnings.append("الإجمالي شامل الضريبة لا يطابق مجموع الإجمالي والضريبة.")

    return warnings


def prepare_zatca_payload(invoice):
    xml_text = XMLGenerator.generate_invoice_xml(invoice.id).decode("utf-8")
    seller = _seller(invoice)
    current_hash = invoice_hash(xml_text)
    qr = QRGenerator.generate_qr(
        seller_name=seller["name"],
        vat_number=seller["vat_number"],
        invoice_datetime=invoice.issue_date,
        total_with_vat=_money(invoice.total_with_vat),
        vat_amount=_money(invoice.total_vat),
        xml_hash=current_hash,
    )
    warnings = validate_invoice(invoice)
    invoice.zatca_xml = xml_text
    invoice.zatca_qr = qr
    invoice.zatca_hash = current_hash
    invoice.zatca_warnings = "\n".join(warnings)
    invoice.zatca_status = "جاهزة للإرسال" if not warnings else "غير مستوفية"
    invoice.save(update_fields=["zatca_xml", "zatca_qr", "zatca_hash", "zatca_warnings", "zatca_status"])
    return {
        "xml": xml_text,
        "xml_base64": base64.b64encode(xml_text.encode("utf-8")).decode("utf-8"),
        "qr": qr,
        "hash": invoice.zatca_hash,
        "warnings": warnings,
        "status": invoice.zatca_status,
    }
