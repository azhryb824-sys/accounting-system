from django.urls import path
from . import tax_views

urlpatterns = [
    path('', tax_views.tax_list, name='tax_list'),
    path('create/', tax_views.tax_create, name='tax_create'),
    path('<int:id>/edit/', tax_views.tax_edit, name='tax_edit'),
    path('<int:id>/delete/', tax_views.tax_delete, name='tax_delete'),
]
