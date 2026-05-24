from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Customer
from .forms import CustomerForm
from accounts.views import role_required


@login_required(login_url='login')
@role_required('view_customer')
def customer_list(request):
    query = request.GET.get('q')

    if query:
        customers = Customer.objects.filter(name__icontains=query)
    else:
        customers = Customer.objects.all()

    return render(request, 'invoicing/customer_list.html', {
        "customers": customers,
        "query": query
    })



@login_required(login_url='login')
@role_required('add_customer')
def customer_add(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('customer_list')
    else:
        form = CustomerForm()

    return render(request, 'invoicing/customer_form.html', {"form": form, "title": "إضافة عميل"})


@login_required(login_url='login')
@role_required('change_customer')
def customer_edit(request, id):
    customer = get_object_or_404(Customer, id=id)

    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            return redirect('customer_list')
    else:
        form = CustomerForm(instance=customer)

    return render(request, 'invoicing/customer_form.html', {"form": form, "title": "تعديل العميل"})


@login_required(login_url='login')
@role_required('delete_customer')
def customer_delete(request, id):
    customer = get_object_or_404(Customer, id=id)
    customer.delete()
    return redirect('customer_list')

@login_required(login_url='login')
@role_required('view_customer')
def customer_detail(request, id):
    customer = get_object_or_404(Customer, id=id)

    return render(request, 'invoicing/customer_detail.html', {
        "customer": customer
    })
