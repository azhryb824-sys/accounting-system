from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Account, Branch, JournalEntry, JournalEntryLine
from core.services.monthly_close import assert_month_open

from accounts.views import role_required
from .forms import InvoiceForm, InvoiceItemFormSet
from .models import Customer, Invoice, InvoiceItem, Item, StockMovement, Tax
from .zatca import prepare_zatca_payload


def post_sales_invoice(invoice):
    assert_month_open(invoice.branch.company, invoice.issue_date.date())
    entry = JournalEntry.objects.create(
        date=invoice.issue_date,
        description=_("Sales Invoice No. {invoice_number}").format(invoice_number=invoice.invoice_number),
        branch=invoice.branch,
    )

    acc_receivable = Account.objects.get(code="1101")
    acc_sales = Account.objects.get(code="4100")
    acc_vat = Account.objects.get(code="2100")
    acc_inventory = Account.objects.get(code="1200")
    acc_cogs = Account.objects.get(code="5100")

    JournalEntryLine.objects.create(
        entry=entry,
        account=acc_receivable,
        debit=invoice.total_with_vat,
        credit=0,
        note=_("Debtor - Customer"),
    )
    JournalEntryLine.objects.create(
        entry=entry,
        account=acc_sales,
        debit=0,
        credit=invoice.total_amount,
        note=_("Sales Revenue"),
    )
    if invoice.total_vat > 0:
        JournalEntryLine.objects.create(
            entry=entry,
            account=acc_vat,
            debit=0,
            credit=invoice.total_vat,
            note=_("Value Added Tax"),
        )

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

    JournalEntryLine.objects.create(
        entry=entry,
        account=acc_cogs,
        debit=total_cogs,
        credit=0,
        note=_("Cost of Goods Sold"),
    )
    JournalEntryLine.objects.create(
        entry=entry,
        account=acc_inventory,
        debit=0,
        credit=total_cogs,
        note=_("Inventory Reduction"),
    )
    return entry


@login_required(login_url='login')
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
def invoice_list(request):
    branch_id = request.session.get('branch_id')
    invoices = Invoice.objects.filter(branch_id=branch_id).order_by('-issue_date')
    return render(request, 'invoicing/invoice_list.html', {"invoices": invoices, "title": _("Sales Invoices List")})


@login_required(login_url='login')
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


@login_required(login_url='login')
def pos_terminal(request):
    return render(request, 'invoicing/pos_terminal.html', {"title": _("POS Terminal")})


@login_required(login_url='login')
def customer_list(request):
    customers = Customer.objects.all()
    return render(request, 'invoicing/customer_list.html', {"customers": customers, "title": _("Customers List")})


@login_required(login_url='login')
def purchase_list(request):
    from .models import PurchaseInvoice

    branch_id = request.session.get('branch_id')
    purchases = PurchaseInvoice.objects.filter(branch_id=branch_id).order_by('-issue_date')
    return render(request, 'invoicing/purchase_list.html', {"purchases": purchases, "title": _("Purchase Invoices")})


@login_required(login_url='login')
def purchase_add(request):
    return render(request, 'invoicing/purchase_form.html', {"title": _("Add Purchase Invoice")})


@login_required(login_url='login')
@role_required('view_item')
def inventory_list(request):
    branch_id = request.session.get('branch_id')
    items = Item.objects.filter(branch_id=branch_id)
    return render(request, 'invoicing/inventory_list.html', {"items": items, "title": _("Inventory List")})


@login_required(login_url='login')
def tax_list(request):
    taxes = Tax.objects.all()
    return render(request, 'invoicing/tax_list.html', {"taxes": taxes, "title": _("Tax Settings")})


@login_required(login_url='login')
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
def product_lookup(request):
    return render(request, 'invoicing/pos_terminal.html', {"title": _("Product Lookup")})
