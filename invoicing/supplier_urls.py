from django.urls import path
from . import supplier_views

urlpatterns = [
    path('', supplier_views.supplier_list, name='supplier_list'),
    path('add/', supplier_views.supplier_add, name='supplier_add'),
    path('<int:id>/edit/', supplier_views.supplier_edit, name='supplier_edit'),
    path('<int:id>/delete/', supplier_views.supplier_delete, name='supplier_delete'),
    path('<int:id>/', supplier_views.supplier_detail, name='supplier_detail'),

]
