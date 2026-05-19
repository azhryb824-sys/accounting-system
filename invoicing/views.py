from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from django.contrib.auth.decorators import login_required
# موديلات الفواتير والمخزون
from .models import Invoice, InvoiceItem, StockMovement, Item

# نماذج الإدخال
from .forms import InvoiceForm, InvoiceItemFormSet

# QR + XML
from .qr_generator import QRGenerator
from .xml_generator import XMLGenerator

# 🔥 استيراد الموديلات المحاسبية من core
from core.models import JournalEntry, JournalEntryLine, Account

from decimal import Decimal
from django.utils.translation import gettext_lazy as _


# ============================
#  دالة Auto Posting لفاتورة المبيعات
# ============================
def post_sales_invoice(invoice):

    entry = JournalEntry.objects.create(
        date=invoice.issue_date,
        description=_("Sales Invoice No. {invoice_number}").format(invoice_number=invoice.invoice_number),
        branch=invoice.branch,
    )

    ACC_RECEIVABLE = Account.objects.get(code="1101")
    ACC_SALES = Account.objects.get(code="4100")
    ACC_VAT = Account.objects.get(code="2100")
    ACC_INVENTORY = Account.objects.get(code="1200")
    ACC_COGS = Account.objects.get(code="5100")

    # العميل (مدين)
    JournalEntryLine.objects.create(
        entry=entry,
        account=ACC_RECEIVABLE,
        debit=invoice.total_with_vat,
        credit=0,
        note=_("Debtor - Customer")
    )

    # المبيعات (دائن)
    JournalEntryLine.objects.create(
        entry=entry,
        account=ACC_SALES,
        debit=0,
        credit=invoice.total_amount, # _("Sales Revenue")
        note=_("Sales Revenue")
    )

    # ضريبة القيمة المضافة (دائن)
    if invoice.total_vat > 0:
        JournalEntryLine.objects.create(
            entry=entry,
            account=ACC_VAT,
            debit=0,
            credit=invoice.total_vat, # _("Value Added Tax")
            note=_("Value Added Tax")
        )

    # COGS + تحديث المخزون
    total_cogs = Decimal("0.00")

    for item in invoice.items.all():

        item_cost = item.item.cost * item.quantity
        total_cogs += item_cost

        # تحديث المخزون
        item.item.quantity -= item.quantity
        item.item.save()

        # حركة مخزون
        StockMovement.objects.create(
            branch=invoice.branch,
            item=item.item,
            quantity=item.quantity,
            movement_type="OUT"
        )

    # COGS (مدين)
    JournalEntryLine.objects.create(
        entry=entry,
        account=ACC_COGS,
        debit=total_cogs,
        credit=0,
        note=_("Cost of Goods Sold")
    )

    # المخزون (دائن)
    JournalEntryLine.objects.create(
        entry=entry,
        account=ACC_INVENTORY,
        debit=0,
        credit=total_cogs, # _("Inventory Reduction")
        note=_("Inventory Reduction")
    )

    return entry



# ============================
#  زر الترحيل (Post Invoice)
# ============================
@login_required(login_url='login')
def post_invoice(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    # منع الترحيل المكرر
    if invoice.is_posted:
        messages.warning(request, _("Invoice has already been posted."))
        return redirect('invoice_detail', id=pk)

    # تنفيذ الترحيل
    entry = post_sales_invoice(invoice)

    # تحديث حالة الفاتورة
    invoice.is_posted = True
    invoice.save()

    messages.success(request, _("Invoice posted and journal entry {entry_id} created successfully.").format(entry_id=entry.id))
    return redirect('invoice_detail', id=pk)



# ============================
#  قائمة الفواتير حسب الفرع
# ============================
@login_required(login_url='login')
def invoice_list(request):
    branch_id = request.session.get('branch_id')
    invoices = Invoice.objects.filter(branch_id=branch_id).order_by('-issue_date')

    return render(request, 'invoicing/invoice_list.html', {
        "invoices": invoices, "title": _("Sales Invoices List")
    })



# ============================
#  تفاصيل الفاتورة
# ============================
@login_required(login_url='login')
def invoice_detail(request, id):
    invoice = get_object_or_404(Invoice, id=id)
    items = InvoiceItem.objects.filter(invoice=invoice)

    qr = QRGenerator.generate_qr(
        seller_name=_("Abdulrahman Company"), # Marked for translation
        vat_number="123456789012345",
        invoice_datetime=invoice.issue_date,
        total_with_vat=invoice.total_with_vat,
        vat_amount=invoice.total_vat
    )

    xml_data = XMLGenerator.generate_invoice_xml(invoice.id).decode('utf-8') # _("Invoice Details")

    return render(request, 'invoicing/invoice_detail.html', {
        "invoice": invoice,
        "items": items,
        "qr": qr,
        "xml_data": xml_data,
        "title": _("Invoice Details")
    })
 # _("Invoice Details")


# ============================
#  إنشاء فاتورة جديدة + Auto Posting
# ============================
@login_required(login_url='login')
def invoice_create(request):
    branch_id = request.session.get('branch_id')

    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        formset = InvoiceItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            invoice = form.save(commit=False)
            invoice.branch_id = branch_id

            total_amount = 0
            total_vat = 0
            total_with_vat = 0

            items = formset.save(commit=False)

            # تحقق من المخزون
            for item in items:
                product = item.item
                if product.quantity < item.quantity:
                    messages.error(request, _("Insufficient stock for item: {item_name}").format(item_name=product.name))
                    return render(request, 'invoicing/invoice_create.html', {
                        'form': form,
                        'formset': formset,
                    })

            # حساب totals
            for item in items:
                item.line_total = item.quantity * item.unit_price
                item.line_vat = item.line_total * (item.tax.rate / 100)
                item.line_total_with_vat = item.line_total + item.line_vat

                total_amount += item.line_total
                total_vat += item.line_vat
                total_with_vat += item.line_total_with_vat

                item.invoice = invoice
                item.branch_id = branch_id

            invoice.total_amount = total_amount
            invoice.total_vat = total_vat
            invoice.total_with_vat = total_with_vat
            invoice.save()

            # حفظ العناصر
            for item in items:
                item.save()

            # 🔥 Auto Posting
            post_sales_invoice(invoice)
            
            # تحديث حالة الفاتورة لمنع التكرار
            invoice.is_posted = True
            invoice.save()

            messages.success(request, _("Invoice created and posted successfully."))
            return redirect('invoice_list')

    else:
        form = InvoiceForm()
        formset = InvoiceItemFormSet()

    return render(request, 'invoicing/invoice_create.html', { # _("Create New Invoice")
        'form': form, # _("Create New Invoice")
        'formset': formset, # _("Create New Invoice")
        "title": _("Create New Invoice")
    })

@login_required(login_url='login')
def pos_terminal(request):
    return render(request, 'invoicing/pos_terminal.html', {"title": _("POS Terminal")})

@login_required(login_url='login')
def customer_list(request):
    # محاولة جلب العملاء إذا كان الموديل موجوداً
    try:
        from .models import Customer
        customers = Customer.objects.all()
    except ImportError:
        customers = []
    return render(request, 'invoicing/customer_list.html', {"customers": customers, "title": _("Customers List")})

@login_required(login_url='login')
def purchase_list(request):
    try:
        from .models import PurchaseInvoice
        branch_id = request.session.get('branch_id')
        purchases = PurchaseInvoice.objects.filter(branch_id=branch_id).order_by('-issue_date')
    except ImportError:
        purchases = []
    return render(request, 'invoicing/purchase_list.html', {"purchases": purchases, "title": _("Purchase Invoices")})

@login_required(login_url='login')
def purchase_add(request):
    return render(request, 'invoicing/purchase_form.html', {"title": _("Add Purchase Invoice")})

@login_required(login_url='login')
def inventory_list(request):
    branch_id = request.session.get('branch_id')
    items = Item.objects.filter(branch_id=branch_id)
    return render(request, 'invoicing/inventory_list.html', {"items": items, "title": _("Inventory List")})

@login_required(login_url='login')
def tax_list(request):
    try:
        from .models import Tax
        taxes = Tax.objects.all()
    except ImportError:
        taxes = []
    return render(request, 'invoicing/tax_list.html', {"taxes": taxes, "title": _("Tax Settings")})

@login_required(login_url='login')
def zatca_dashboard(request):
    return render(request, 'invoicing/zatca_dashboard.html', {"title": _("ZATCA Dashboard")})

@login_required(login_url='login')
def product_lookup(request):
    return render(request, 'invoicing/pos_terminal.html', {"title": _("Product Lookup")})
