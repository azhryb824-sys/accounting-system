from django.urls import path
from . import purchase_views

urlpatterns = [
    path('', purchase_views.purchase_list, name='purchase_list'),
    path('add/', purchase_views.purchase_add, name='purchase_add'),
    path('<int:id>/edit/', purchase_views.purchase_edit, name='purchase_edit'),
    path('<int:id>/delete/', purchase_views.purchase_delete, name='purchase_delete'),
    path('inventory/', purchase_views.inventory_list, name='inventory_list'),
    path('inventory/add/', purchase_views.item_add, name='item_add'),
    path('inventory/<int:item_id>/edit/', purchase_views.item_edit, name='item_edit'),
]
