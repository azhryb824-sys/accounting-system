from django.shortcuts import render
from .models import Item

def inventory_list(request):
    items = Item.objects.all()
    return render(request, 'invoicing/inventory_list.html', {"items": items})
