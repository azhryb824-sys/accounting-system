from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from .models import PurchaseInvoice, PurchaseItem, Supplier, Item, StockMovement
from django.utils.translation import gettext_lazy as _
from .forms import PurchaseInvoiceForm

# ============================
#  قائمة فواتير المشتريات حسب الفرع
# ============================
@login_required(login_url='login')
def purchase_list(request):
    branch_id = request.session.get('branch_id')
    purchases = PurchaseInvoice.objects.filter(branch_id=branch_id).order_by('-issue_date')

    return render(request, 'invoicing/purchase_list.html', {
        "purchases": purchases, "title": _("Purchase Invoices List")
    })


# ============================
#  إضافة فاتورة مشتريات
# ============================
@login_required(login_url='login')
def purchase_add(request):
    branch_id = request.session.get('branch_id')

    if request.method == 'POST':
        form = PurchaseInvoiceForm(request.POST)

        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.branch_id = branch_id
            invoice.save()

            items = request.POST.getlist("item_id")
            quantities = request.POST.getlist("quantity")
            prices = request.POST.getlist("price")

            for i in range(len(items)):
                purchase_item = PurchaseItem.objects.create(
                    invoice=invoice,
                    branch_id=branch_id,
                    item_id=items[i],
                    quantity=quantities[i],
                    price=prices[i]
                )

                # تحديث كمية المخزون الفعلي للصنف
                item_obj = purchase_item.item
                item_obj.quantity += purchase_item.quantity
                item_obj.save()

                # حركة مخزون IN
                StockMovement.objects.create(
                    branch_id=branch_id,
                    item=purchase_item.item,
                    quantity=purchase_item.quantity,
                    movement_type="IN"
                )

            messages.success(request, _("Purchase invoice added and inventory updated successfully."))
            return redirect('purchase_list')

    else:
        form = PurchaseInvoiceForm()

    return render(request, 'invoicing/purchase_form.html', {
        "form": form, "title": _("Add Purchase Invoice")
    })


# ============================
#  تعديل فاتورة مشتريات
# ============================
@login_required(login_url='login')
def purchase_edit(request, id):
    purchase = get_object_or_404(PurchaseInvoice, id=id)

    if request.method == 'POST':
        form = PurchaseInvoiceForm(request.POST, instance=purchase)
        if form.is_valid():
            form.save()
            messages.success(request, _("Purchase invoice updated successfully."))
            return redirect('purchase_list')

    else:
        form = PurchaseInvoiceForm(instance=purchase)

    return render(request, 'invoicing/purchase_form.html', {
        "form": form, "title": _("Edit Purchase Invoice")
    })


# ============================
#  حذف فاتورة مشتريات
# ============================
@login_required(login_url='login')
def purchase_delete(request, id):
    purchase = get_object_or_404(PurchaseInvoice, id=id)
    purchase.delete()
    messages.success(request, _("Purchase invoice deleted successfully."))
    return redirect('purchase_list')

# ============================
#  قائمة المخزون حسب الفرع
# ============================
@login_required(login_url='login')
def inventory_list(request):
    branch_id = request.session.get('branch_id')
    items = Item.objects.filter(branch_id=branch_id)

    return render(request, 'invoicing/inventory_list.html', {
        "items": items, "title": _("Inventory List")
    })
