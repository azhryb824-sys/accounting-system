import base64
import hashlib
from decimal import Decimal

from django.conf import settings

from .qr_generator import QRGenerator
from .xml_generator import XMLGenerator


def invoice_hash(xml_text):
    return hashlib.sha256(xml_text.encode("utf-8")).hexdigest()


def validate_invoice(invoice):
    warnings = []
    seller_name = getattr(settings, "COMPANY_NAME", "") or invoice.branch.company.name
    seller_vat = getattr(settings, "COMPANY_VAT_NUMBER", "") or invoice.branch.company.vat_number

    if not seller_name:
        warnings.append("اسم البائع غير مكتمل.")
    if not seller_vat or len(str(seller_vat)) != 15:
        warnings.append("الرقم الضريبي للبائع يجب أن يكون 15 رقماً.")
    if invoice.invoice_type == "standard" and not invoice.customer.vat_number:
        warnings.append("الفاتورة الضريبية تتطلب رقماً ضريبياً للعميل.")
    if invoice.total_with_vat <= Decimal("0"):
        warnings.append("إجمالي الفاتورة يجب أن يكون أكبر من صفر.")
    if not invoice.items.exists():
        warnings.append("الفاتورة لا تحتوي على بنود.")

    return warnings


def prepare_zatca_payload(invoice):
    xml_text = XMLGenerator.generate_invoice_xml(invoice.id).decode("utf-8")
    seller_name = getattr(settings, "COMPANY_NAME", "") or invoice.branch.company.name
    seller_vat = getattr(settings, "COMPANY_VAT_NUMBER", "") or invoice.branch.company.vat_number or ""
    current_hash = invoice_hash(xml_text)
    qr = QRGenerator.generate_qr(
        seller_name=seller_name,
        vat_number=str(seller_vat),
        invoice_datetime=invoice.issue_date,
        total_with_vat=invoice.total_with_vat,
        vat_amount=invoice.total_vat,
        xml_hash=current_hash,
    )
    warnings = validate_invoice(invoice)
    invoice.zatca_xml = xml_text
    invoice.zatca_qr = qr
    invoice.zatca_hash = current_hash
    invoice.zatca_warnings = "\n".join(warnings)
    invoice.zatca_status = "جاهزة" if not warnings else "تحتاج مراجعة"
    invoice.save(update_fields=["zatca_xml", "zatca_qr", "zatca_hash", "zatca_warnings", "zatca_status"])
    return {
        "xml": xml_text,
        "xml_base64": base64.b64encode(xml_text.encode("utf-8")).decode("utf-8"),
        "qr": qr,
        "hash": invoice.zatca_hash,
        "warnings": warnings,
        "status": invoice.zatca_status,
    }
