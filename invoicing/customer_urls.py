from django.urls import path
from . import customer_views

urlpatterns = [
    path('', customer_views.customer_list, name='customer_list'),
    path('add/', customer_views.customer_add, name='customer_add'),
    path('<int:id>/edit/', customer_views.customer_edit, name='customer_edit'),
    path('<int:id>/delete/', customer_views.customer_delete, name='customer_delete'),
    path('<int:id>/', customer_views.customer_detail, name='customer_detail'),

]
