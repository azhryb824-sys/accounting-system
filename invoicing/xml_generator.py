from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from lxml import etree

from .models import Invoice


CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
EXT = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"


def _money(value):
    return str(Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _el(parent, namespace, tag, text=None, **attrs):
    node = etree.SubElement(parent, f"{{{namespace}}}{tag}", **attrs)
    if text is not None:
        node.text = str(text)
    return node


class XMLGenerator:
    @staticmethod
    def generate_invoice_xml(invoice_id):
        invoice = Invoice.objects.select_related("branch__company", "customer").get(id=invoice_id)
        company = invoice.branch.company
        seller_name = getattr(settings, "COMPANY_NAME", "") or company.name
        seller_vat = getattr(settings, "COMPANY_VAT_NUMBER", "") or company.vat_number or ""

        nsmap = {
            None: "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
            "cbc": CBC,
            "cac": CAC,
            "ext": EXT,
        }
        root = etree.Element("Invoice", nsmap=nsmap)

        extensions = _el(root, EXT, "UBLExtensions")
        extension = _el(extensions, EXT, "UBLExtension")
        _el(extension, EXT, "ExtensionContent")

        _el(root, CBC, "ProfileID", "reporting:1.0")
        _el(root, CBC, "ID", invoice.invoice_number)
        _el(root, CBC, "UUID", invoice.uuid)
        _el(root, CBC, "IssueDate", invoice.issue_date.strftime("%Y-%m-%d"))
        _el(root, CBC, "IssueTime", invoice.issue_date.strftime("%H:%M:%S"))
        _el(root, CBC, "InvoiceTypeCode", "388" if invoice.invoice_type == "standard" else "388", name="0100000")
        _el(root, CBC, "DocumentCurrencyCode", "SAR")
        _el(root, CBC, "TaxCurrencyCode", "SAR")

        supplier = _el(root, CAC, "AccountingSupplierParty")
        supplier_party = _el(supplier, CAC, "Party")
        supplier_id = _el(supplier_party, CAC, "PartyIdentification")
        _el(supplier_id, CBC, "ID", company.unified_number, schemeID="CRN")
        supplier_address = _el(supplier_party, CAC, "PostalAddress")
        _el(supplier_address, CBC, "StreetName", company.address or invoice.branch.address or "Saudi Arabia")
        _el(supplier_address, CBC, "CityName", "Saudi Arabia")
        _el(supplier_address, CBC, "PostalZone", "00000")
        supplier_country = _el(supplier_address, CAC, "Country")
        _el(supplier_country, CBC, "IdentificationCode", "SA")
        supplier_tax = _el(supplier_party, CAC, "PartyTaxScheme")
        _el(supplier_tax, CBC, "CompanyID", seller_vat)
        supplier_scheme = _el(supplier_tax, CAC, "TaxScheme")
        _el(supplier_scheme, CBC, "ID", "VAT")
        supplier_legal = _el(supplier_party, CAC, "PartyLegalEntity")
        _el(supplier_legal, CBC, "RegistrationName", seller_name)

        customer = _el(root, CAC, "AccountingCustomerParty")
        customer_party = _el(customer, CAC, "Party")
        if invoice.customer.vat_number:
            customer_tax = _el(customer_party, CAC, "PartyTaxScheme")
            _el(customer_tax, CBC, "CompanyID", invoice.customer.vat_number)
            customer_scheme = _el(customer_tax, CAC, "TaxScheme")
            _el(customer_scheme, CBC, "ID", "VAT")
        customer_legal = _el(customer_party, CAC, "PartyLegalEntity")
        _el(customer_legal, CBC, "RegistrationName", invoice.customer.name)

        tax_total = _el(root, CAC, "TaxTotal")
        _el(tax_total, CBC, "TaxAmount", _money(invoice.total_vat), currencyID="SAR")

        monetary = _el(root, CAC, "LegalMonetaryTotal")
        _el(monetary, CBC, "LineExtensionAmount", _money(invoice.total_amount), currencyID="SAR")
        _el(monetary, CBC, "TaxExclusiveAmount", _money(invoice.total_amount), currencyID="SAR")
        _el(monetary, CBC, "TaxInclusiveAmount", _money(invoice.total_with_vat), currencyID="SAR")
        _el(monetary, CBC, "PayableAmount", _money(invoice.total_with_vat), currencyID="SAR")

        for index, item in enumerate(invoice.items.select_related("tax", "item"), start=1):
            line = _el(root, CAC, "InvoiceLine")
            _el(line, CBC, "ID", index)
            _el(line, CBC, "InvoicedQuantity", _money(item.quantity), unitCode="PCE")
            _el(line, CBC, "LineExtensionAmount", _money(item.line_total), currencyID="SAR")
            line_tax = _el(line, CAC, "TaxTotal")
            _el(line_tax, CBC, "TaxAmount", _money(item.line_vat), currencyID="SAR")
            line_item = _el(line, CAC, "Item")
            _el(line_item, CBC, "Name", item.description or item.item.name)
            category = _el(line_item, CAC, "ClassifiedTaxCategory")
            _el(category, CBC, "ID", "S")
            _el(category, CBC, "Percent", _money(item.tax.rate))
            category_scheme = _el(category, CAC, "TaxScheme")
            _el(category_scheme, CBC, "ID", "VAT")
            price = _el(line, CAC, "Price")
            _el(price, CBC, "PriceAmount", _money(item.unit_price), currencyID="SAR")

        return etree.tostring(root, pretty_print=True, encoding="UTF-8", xml_declaration=True)
