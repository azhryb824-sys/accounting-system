from decimal import Decimal
from io import BytesIO
import json
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Branch
from core.services.accounting import create_balanced_entry
from core.services.monthly_close import assert_month_open

from accounts.views import role_required
from .forms import InvoiceForm, InvoiceItemFormSet, QuoteForm, QuoteItemFormSet
from .models import Customer, Invoice, InvoiceItem, Item, Quote, QuoteItem, StockMovement, Tax
from .zatca import prepare_zatca_payload


def _selected_branch(request):
    company_id = request.session.get("company_id")
    branch_id = request.session.get("branch_id")
    if not company_id or not branch_id:
        return None
    return Branch.objects.filter(id=branch_id, company_id=company_id).first()


def post_sales_invoice(invoice):
    if invoice.journal_entry_id:
        return invoice.journal_entry
    assert_month_open(invoice.branch.company, invoice.issue_date.date())
    total_cogs = Decimal("0.00")
    for line in invoice.items.select_related("item"):
        item_cost = line.item.cost * line.quantity
        total_cogs += item_cost
        line.item.quantity -= line.quantity
        line.item.save(update_fields=["quantity"])
        StockMovement.objects.create(
            branch=invoice.branch,
            item=line.item,
            quantity=line.quantity,
            movement_type="OUT",
        )

    debit_account = "1101" if invoice.payment_method == "ط¢ط¬ظ„" else "1000"
    debit_note = _("Debtor - Customer") if debit_account == "1101" else _("Cash / Bank")
    entry = create_balanced_entry(
        branch=invoice.branch,
        date=invoice.issue_date.date(),
        description=_("Sales Invoice No. {invoice_number}").format(invoice_number=invoice.invoice_number),
        lines=[
            {"account": debit_account, "debit": invoice.total_with_vat, "note": debit_note},
            {"account": "4100", "credit": invoice.total_amount, "note": _("Sales Revenue")},
            {"account": "2100", "credit": invoice.total_vat, "note": _("Value Added Tax")},
            {"account": "5100", "debit": total_cogs, "note": _("Cost of Goods Sold")},
            {"account": "1200", "credit": total_cogs, "note": _("Inventory Reduction")},
        ],
    )
    invoice.journal_entry = entry
    invoice.save(update_fields=["journal_entry"])
    return entry


@login_required(login_url='login')
@role_required('change_invoice')
def post_invoice(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if invoice.is_posted:
        messages.warning(request, _("Invoice has already been posted."))
        return redirect('invoice_detail', id=pk)

    zatca_payload = prepare_zatca_payload(invoice)
    if zatca_payload["warnings"]:
        for warning in zatca_payload["warnings"]:
            messages.error(request, warning)
        messages.error(request, "لا يمكن ترحيل الفاتورة قبل استيفاء متطلبات هيئة الزكاة والضريبة والجمارك.")
        return redirect('invoice_detail', id=pk)

    entry = post_sales_invoice(invoice)
    invoice.is_posted = True
    invoice.save(update_fields=["is_posted"])
    messages.success(request, _("Invoice posted and journal entry {entry_id} created successfully.").format(entry_id=entry.id))
    return redirect('invoice_detail', id=pk)


@login_required(login_url='login')
@role_required('view_invoice')
def invoice_list(request):
    branch_id = request.session.get('branch_id')
    invoices = Invoice.objects.filter(branch_id=branch_id).order_by('-issue_date')
    return render(request, 'invoicing/invoice_list.html', {"invoices": invoices, "title": _("Sales Invoices List")})


@login_required(login_url='login')
@role_required('view_invoice')
def invoice_detail(request, id):
    invoice = get_object_or_404(Invoice, id=id)
    items = InvoiceItem.objects.filter(invoice=invoice)
    zatca_payload = prepare_zatca_payload(invoice)
    return render(request, 'invoicing/invoice_detail.html', {
        "invoice": invoice,
        "items": items,
        "qr": zatca_payload["qr"],
        "xml_data": zatca_payload["xml"],
        "zatca_warnings": zatca_payload["warnings"],
        "title": _("Invoice Details"),
    })


@login_required(login_url='login')
@role_required('add_invoice')
def invoice_create(request):
    branch_id = request.session.get('branch_id')
    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        formset = InvoiceItemFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            invoice = form.save(commit=False)
            invoice.branch_id = branch_id
            branch = get_object_or_404(Branch, id=branch_id)
            assert_month_open(branch.company, timezone.localdate())
            total_amount = Decimal("0.00")
            total_vat = Decimal("0.00")
            total_with_vat = Decimal("0.00")
            items = formset.save(commit=False)

            for line in items:
                product = line.item
                if product.quantity < line.quantity:
                    messages.error(request, _("Insufficient stock for item: {item_name}").format(item_name=product.name))
                    return render(request, 'invoicing/invoice_create.html', {'form': form, 'formset': formset})

            for line in items:
                line.line_total = line.quantity * line.unit_price
                line.line_vat = line.line_total * (line.tax.rate / Decimal("100"))
                line.line_total_with_vat = line.line_total + line.line_vat
                total_amount += line.line_total
                total_vat += line.line_vat
                total_with_vat += line.line_total_with_vat
                line.invoice = invoice
                line.branch_id = branch_id

            invoice.total_amount = total_amount
            invoice.total_vat = total_vat
            invoice.total_with_vat = total_with_vat
            invoice.save()
            for line in items:
                line.save()

            zatca_payload = prepare_zatca_payload(invoice)
            if zatca_payload["warnings"]:
                for warning in zatca_payload["warnings"]:
                    messages.error(request, warning)
                messages.error(request, "تم حفظ الفاتورة كمسودة، ولن يتم ترحيلها حتى تستوفي متطلبات هيئة الزكاة والضريبة والجمارك.")
                return redirect('invoice_detail', id=invoice.id)

            post_sales_invoice(invoice)
            invoice.is_posted = True
            invoice.save(update_fields=["is_posted"])
            messages.success(request, _("Invoice created and posted successfully."))
            return redirect('invoice_list')
    else:
        form = InvoiceForm()
        formset = InvoiceItemFormSet()

    return render(request, 'invoicing/invoice_create.html', {
        'form': form,
        'formset': formset,
        "title": _("Create New Invoice"),
    })


def _quote_totals(lines):
    total_amount = Decimal("0.00")
    total_vat = Decimal("0.00")
    total_with_vat = Decimal("0.00")
    for line in lines:
        line.line_total = line.quantity * line.unit_price
        line.line_vat = line.line_total * (line.tax_rate / Decimal("100"))
        line.line_total_with_vat = line.line_total + line.line_vat
        total_amount += line.line_total
        total_vat += line.line_vat
        total_with_vat += line.line_total_with_vat
    return total_amount, total_vat, total_with_vat


@login_required(login_url='login')
@role_required('view_invoice')
def quote_list(request):
    branch_id = request.session.get('branch_id')
    quotes = Quote.objects.filter(branch_id=branch_id).select_related("customer").order_by("-created_at")
    return render(request, 'invoicing/quote_list.html', {"quotes": quotes, "title": "عروض الأسعار"})


@login_required(login_url='login')
@role_required('view_invoice')
def quote_detail(request, id):
    quote = get_object_or_404(Quote.objects.select_related("branch__company", "customer"), id=id)
    items = QuoteItem.objects.filter(quote=quote)
    return render(request, 'invoicing/quote_detail.html', {"quote": quote, "items": items, "title": "تفاصيل عرض السعر"})


@login_required(login_url='login')
@role_required('add_invoice')
def quote_create(request):
    branch_id = request.session.get('branch_id')
    if request.method == 'POST':
        form = QuoteForm(request.POST)
        formset = QuoteItemFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            quote = form.save(commit=False)
            quote.branch_id = branch_id
            items = formset.save(commit=False)
            for line in items:
                line.branch_id = branch_id
            quote.total_amount, quote.total_vat, quote.total_with_vat = _quote_totals(items)
            quote.save()
            for line in items:
                line.quote = quote
                line.save()
            messages.success(request, "تم إنشاء عرض السعر. لا يوجد أثر محاسبي حتى يتم تحويله إلى فاتورة.")
            return redirect('quote_detail', id=quote.id)
    else:
        form = QuoteForm(initial={"quote_number": f"Q-{timezone.now().strftime('%Y%m%d%H%M%S')}"})
        formset = QuoteItemFormSet()
    return render(request, 'invoicing/quote_create.html', {"form": form, "formset": formset, "title": "إنشاء عرض سعر"})


def _pdf_arabic(text):
    from arabic_reshaper import reshape
    from bidi.algorithm import get_display

    return get_display(reshape(str(text or "")))


def _register_pdf_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("ArabicFont", path))
                return "ArabicFont"
            except Exception:
                continue
    return "Helvetica"


@login_required(login_url='login')
@role_required('view_invoice')
def quote_pdf(request, id):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    quote = get_object_or_404(Quote.objects.select_related("branch__company", "customer"), id=id)
    items = list(QuoteItem.objects.filter(quote=quote))
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    font = _register_pdf_font()

    def draw_right(text, y, size=11, bold=False):
        pdf.setFont(font, size)
        pdf.drawRightString(width - 2 * cm, y, _pdf_arabic(text))

    pdf.setFillColor(colors.HexColor("#0f766e"))
    pdf.rect(0, height - 4.2 * cm, width, 4.2 * cm, stroke=0, fill=1)
    pdf.setFillColor(colors.white)
    draw_right("عرض سعر", height - 1.5 * cm, 22)
    draw_right(f"رقم: {quote.quote_number}", height - 2.4 * cm, 12)
    draw_right(f"التاريخ: {quote.issue_date:%Y-%m-%d}", height - 3.1 * cm, 11)
    if quote.valid_until:
        draw_right(f"صالح حتى: {quote.valid_until:%Y-%m-%d}", height - 3.7 * cm, 11)

    y = height - 5.2 * cm
    pdf.setFillColor(colors.HexColor("#111827"))
    draw_right(f"الشركة: {quote.branch.company.name}", y, 12)
    draw_right(f"الفرع: {quote.branch.name}", y - 0.6 * cm, 11)
    draw_right(f"العميل: {quote.customer.name}", y - 1.2 * cm, 11)

    y -= 2.2 * cm
    headers = ["الإجمالي", "الضريبة", "السعر", "الكمية", "الوصف"]
    col_x = [2.2 * cm, 5.0 * cm, 7.3 * cm, 9.6 * cm, width - 2 * cm]
    pdf.setFillColor(colors.HexColor("#e0f2f1"))
    pdf.rect(1.5 * cm, y - 0.25 * cm, width - 3 * cm, 0.8 * cm, stroke=0, fill=1)
    pdf.setFillColor(colors.HexColor("#0f172a"))
    pdf.setFont(font, 10)
    for header, x in zip(headers, col_x):
        pdf.drawRightString(x, y, _pdf_arabic(header))
    y -= 0.75 * cm
    pdf.setStrokeColor(colors.HexColor("#d1d5db"))
    for line in items:
        if y < 4 * cm:
            pdf.showPage()
            y = height - 2 * cm
            pdf.setFont(font, 10)
        values = [
            f"{line.line_total_with_vat:.2f}",
            f"{line.line_vat:.2f}",
            f"{line.unit_price:.2f}",
            f"{line.quantity:.2f}",
            line.description,
        ]
        for value, x in zip(values, col_x):
            pdf.drawRightString(x, y, _pdf_arabic(value))
        pdf.line(1.5 * cm, y - 0.25 * cm, width - 1.5 * cm, y - 0.25 * cm)
        y -= 0.65 * cm

    y -= 0.4 * cm
    draw_right(f"الإجمالي قبل الضريبة: {quote.total_amount:.2f}", y, 11)
    draw_right(f"ضريبة القيمة المضافة: {quote.total_vat:.2f}", y - 0.6 * cm, 11)
    pdf.setFillColor(colors.HexColor("#0f766e"))
    draw_right(f"الإجمالي شامل الضريبة: {quote.total_with_vat:.2f}", y - 1.25 * cm, 14)
    pdf.setFillColor(colors.HexColor("#111827"))
    if quote.notes:
        draw_right(f"ملاحظات: {quote.notes}", y - 2.2 * cm, 10)
    draw_right("هذا عرض سعر ولا يعد فاتورة ضريبية ولا يترتب عليه أثر محاسبي حتى اعتماده كفاتورة.", 1.8 * cm, 9)
    pdf.save()
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename=f"quote-{quote.quote_number}.pdf")


@login_required(login_url='login')
@role_required('add_invoice')
def pos_terminal(request):
    branch = _selected_branch(request)
    if not branch:
        messages.warning(request, _("Please select a company and branch before opening the POS terminal."))
        return redirect("select_company_branch")
    return render(request, 'invoicing/pos_terminal.html', {
        "title": _("POS Terminal"),
        "customers": Customer.objects.all().order_by("name"),
        "products": Item.objects.filter(branch=branch, is_active=True).order_by("name")[:12],
        "branch": branch,
        "company": branch.company,
    })


@login_required(login_url='login')
@role_required('view_customer')
def customer_list(request):
    customers = Customer.objects.all()
    return render(request, 'invoicing/customer_list.html', {"customers": customers, "title": _("Customers List")})


@login_required(login_url='login')
@role_required('view_purchaseinvoice')
def purchase_list(request):
    from .models import PurchaseInvoice

    branch_id = request.session.get('branch_id')
    purchases = PurchaseInvoice.objects.filter(branch_id=branch_id).order_by('-issue_date')
    return render(request, 'invoicing/purchase_list.html', {"purchases": purchases, "title": _("Purchase Invoices")})


@login_required(login_url='login')
@role_required('add_purchaseinvoice')
def purchase_add(request):
    return render(request, 'invoicing/purchase_form.html', {"title": _("Add Purchase Invoice")})


@login_required(login_url='login')
@role_required('view_item')
def inventory_list(request):
    branch_id = request.session.get('branch_id')
    items = Item.objects.filter(branch_id=branch_id)
    return render(request, 'invoicing/inventory_list.html', {"items": items, "title": _("Inventory List")})


@login_required(login_url='login')
@role_required('view_tax')
def tax_list(request):
    taxes = Tax.objects.all()
    return render(request, 'invoicing/tax_list.html', {"taxes": taxes, "title": _("Tax Settings")})


@login_required(login_url='login')
@role_required('view_invoice')
def zatca_dashboard(request):
    branch_id = request.session.get('branch_id')
    invoices = Invoice.objects.filter(branch_id=branch_id).order_by('-issue_date')[:50]
    ready_count = Invoice.objects.filter(branch_id=branch_id, zatca_status="جاهزة للإرسال").count()
    blocked_count = Invoice.objects.filter(branch_id=branch_id, zatca_status="غير مستوفية").count()
    posted_count = Invoice.objects.filter(branch_id=branch_id, is_posted=True).count()
    return render(request, 'invoicing/zatca_dashboard.html', {
        "title": "متابعة الفوترة الإلكترونية",
        "invoices": invoices,
        "ready_count": ready_count,
        "blocked_count": blocked_count,
        "posted_count": posted_count,
    })


@login_required(login_url='login')
@role_required('add_invoice')
def product_lookup(request):
    branch = _selected_branch(request)
    if not branch:
        return JsonResponse({"ok": False, "message": _("Please select a company and branch first.")}, status=403)
    barcode = (request.GET.get("barcode") or "").strip()
    query = (request.GET.get("q") or "").strip()
    products = Item.objects.filter(branch=branch, is_active=True)
    if barcode:
        product = products.filter(barcode=barcode).first()
    elif query:
        product = products.filter(name__icontains=query).first()
    else:
        return JsonResponse({"ok": False, "message": _("Enter a barcode or product name.")})

    if not product:
        return JsonResponse({"ok": False, "message": _("Product was not found.")}, status=404)

    return JsonResponse({
        "ok": True,
        "product": {
            "id": product.id,
            "name": product.name,
            "price": str(product.selling_price or product.cost),
            "quantity": str(product.quantity),
            "stock": str(product.quantity),
        },
    })


@login_required(login_url='login')
@role_required('add_invoice')
def pos_checkout(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": _("POST is required.")}, status=405)

    branch = _selected_branch(request)
    if not branch:
        return JsonResponse({"ok": False, "message": _("Please select a company and branch first.")}, status=403)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "message": _("Invalid checkout payload.")}, status=400)

    lines = payload.get("lines") or []
    if not lines:
        return JsonResponse({"ok": False, "message": _("Cart is empty.")}, status=400)

    customer_id = payload.get("customer_id")
    if customer_id:
        customer = get_object_or_404(Customer, id=customer_id)
    else:
        customer, created_customer = Customer.objects.get_or_create(
            name="عميل نقدي",
            defaults={"country": "SA"},
        )

    tax, created_tax = Tax.objects.get_or_create(name="VAT 15%", defaults={"rate": Decimal("15.00")})
    invoice_number = f"POS-{timezone.now().strftime('%Y%m%d%H%M%S')}-{Invoice.objects.count() + 1}"
    payment_method = payload.get("payment_method") or "نقدي"

    with transaction.atomic():
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
            item = get_object_or_404(Item.objects.select_for_update(), id=row.get("id"), branch=branch)
            quantity = Decimal(str(row.get("quantity") or "0"))
            unit_price = Decimal(str(row.get("price") or item.selling_price or item.cost or "0"))
            if quantity <= 0:
                return JsonResponse({"ok": False, "message": _("Quantity must be greater than zero.")}, status=400)
            if item.quantity < quantity:
                return JsonResponse({
                    "ok": False,
                    "message": _("Insufficient stock for item: {item_name}").format(item_name=item.name),
                }, status=400)

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
        if zatca_payload["warnings"]:
            invoice.zatca_warnings = "\n".join(str(warning) for warning in zatca_payload["warnings"])
            invoice.zatca_status = "غير مستوفية"
            invoice.save(update_fields=["zatca_warnings", "zatca_status"])
        else:
            post_sales_invoice(invoice)
            invoice.is_posted = True
            invoice.zatca_qr = zatca_payload["qr"]
            invoice.zatca_xml = zatca_payload["xml"]
            invoice.zatca_hash = zatca_payload["hash"]
            invoice.zatca_status = "جاهزة للإرسال"
            invoice.save(update_fields=["is_posted", "zatca_qr", "zatca_xml", "zatca_hash", "zatca_status", "journal_entry"])

    return JsonResponse({
        "ok": True,
        "invoice_number": invoice.invoice_number,
        "zatca_status": invoice.zatca_status,
        "detail_url": f"/invoicing/{invoice.id}/",
    })
