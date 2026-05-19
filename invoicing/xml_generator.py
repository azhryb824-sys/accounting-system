from lxml import etree
from django.conf import settings
from .models import Invoice, InvoiceItem

class XMLGenerator:

    @staticmethod
    def generate_invoice_xml(invoice_id):
        invoice = Invoice.objects.get(id=invoice_id)
        items = InvoiceItem.objects.filter(invoice=invoice)

        # UBL Namespaces
        NSMAP = {
            None: "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
        }

        root = etree.Element("Invoice", nsmap=NSMAP)

        # UUID
        uuid_el = etree.SubElement(root, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}UUID")
        uuid_el.text = str(invoice.uuid)

        # Invoice Number
        id_el = etree.SubElement(root, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID")
        id_el.text = invoice.invoice_number

        # Issue Date
        issue_date = etree.SubElement(root, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}IssueDate")
        issue_date.text = invoice.issue_date.strftime("%Y-%m-%d")

        # Invoice Type
        type_code = etree.SubElement(root, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}InvoiceTypeCode")
        type_code.text = "388" if invoice.invoice_type == "standard" else "381"

        # Supplier
        supplier = etree.SubElement(root, "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}AccountingSupplierParty")
        supplier_party = etree.SubElement(supplier, "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}Party")
        supplier_name = etree.SubElement(supplier_party, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}Name")
        supplier_name.text = settings.COMPANY_NAME

        # Customer
        customer = etree.SubElement(root, "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}AccountingCustomerParty")
        customer_party = etree.SubElement(customer, "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}Party")
        customer_name = etree.SubElement(customer_party, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}Name")
        customer_name.text = invoice.customer.name

        # Invoice Lines
        for item in items:
            line = etree.SubElement(root, "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}InvoiceLine")

            qty = etree.SubElement(line, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}InvoicedQuantity")
            qty.text = str(item.quantity)

            price = etree.SubElement(line, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}PriceAmount")
            price.text = str(item.unit_price)

            line_ext = etree.SubElement(line, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}LineExtensionAmount")
            line_ext.text = str(item.line_total)

            tax_total = etree.SubElement(line, "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}TaxTotal")
            tax_amount = etree.SubElement(tax_total, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}TaxAmount")
            tax_amount.text = str(item.line_vat)

        # Totals
        legal_monetary = etree.SubElement(root, "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}LegalMonetaryTotal")

        payable = etree.SubElement(legal_monetary, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}PayableAmount")
        payable.text = str(invoice.total_with_vat)

        return etree.tostring(root, pretty_print=True, encoding="UTF-8", xml_declaration=True)
