from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Tax
from .forms import TaxForm
from accounts.views import role_required


@login_required(login_url='login')
@role_required('view_tax')
def tax_list(request):
    taxes = Tax.objects.all()
    return render(request, 'invoicing/tax_list.html', {"taxes": taxes})


@login_required(login_url='login')
@role_required('add_tax')
def tax_create(request):
    if request.method == 'POST':
        form = TaxForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('tax_list')
    else:
        form = TaxForm()

    return render(request, 'invoicing/tax_form.html', {"form": form, "title": "إضافة ضريبة"})


@login_required(login_url='login')
@role_required('change_tax')
def tax_edit(request, id):
    tax = get_object_or_404(Tax, id=id)

    if request.method == 'POST':
        form = TaxForm(request.POST, instance=tax)
        if form.is_valid():
            form.save()
            return redirect('tax_list')
    else:
        form = TaxForm(instance=tax)

    return render(request, 'invoicing/tax_form.html', {"form": form, "title": "تعديل الضريبة"})


@login_required(login_url='login')
@role_required('delete_tax')
def tax_delete(request, id):
    tax = get_object_or_404(Tax, id=id)
    tax.delete()
    return redirect('tax_list')
