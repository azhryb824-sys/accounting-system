from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Supplier
from .forms import SupplierForm
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext_lazy as _

@login_required(login_url='login')
def supplier_list(request):
    suppliers = Supplier.objects.all()
    return render(request, 'invoicing/supplier_list.html', {"suppliers": suppliers, "title": _("Suppliers List")})

@login_required(login_url='login')
def supplier_add(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('supplier_list')
    else:
        form = SupplierForm()

    return render(request, 'invoicing/supplier_form.html', {"form": form, "title": _("Add Supplier")})

@login_required(login_url='login')
def supplier_edit(request, id):
    supplier = get_object_or_404(Supplier, id=id)

    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            return redirect('supplier_list')
    else:
        form = SupplierForm(instance=supplier)

    return render(request, 'invoicing/supplier_form.html', {"form": form, "title": _("Edit Supplier")})

@login_required(login_url='login')
def supplier_delete(request, id):
    supplier = get_object_or_404(Supplier, id=id)
    supplier.delete()
    messages.success(request, _("Supplier deleted successfully."))
    return redirect('supplier_list')
@login_required(login_url='login')
def supplier_detail(request, id):
    supplier = get_object_or_404(Supplier, id=id)
    purchases = supplier.purchase_invoices.all()  # من related_name

    total_spent = sum(p.total_with_vat for p in purchases)
    invoice_count = purchases.count()

    return render(request, 'invoicing/supplier_detail.html', {
        "supplier": supplier,
        "purchases": purchases,
        "total_spent": total_spent,
        "invoice_count": invoice_count,
    })
