from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Tax
from .forms import TaxForm


@login_required(login_url='login')
def tax_list(request):
    taxes = Tax.objects.all()
    return render(request, 'invoicing/tax_list.html', {"taxes": taxes})


@login_required(login_url='login')
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
def tax_delete(request, id):
    tax = get_object_or_404(Tax, id=id)
    tax.delete()
    return redirect('tax_list')
