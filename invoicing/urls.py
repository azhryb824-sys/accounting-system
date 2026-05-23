from django.urls import include, path
from . import views

urlpatterns = [
    path('', views.invoice_list, name='invoice_list'),
    path('create/', views.invoice_create, name='invoice_create'),
    path('<int:id>/', views.invoice_detail, name='invoice_detail'),
    path('customers/', include('invoicing.customer_urls')),
    path('taxes/', include('invoicing.tax_urls')),
    path('suppliers/', include('invoicing.supplier_urls')),
    path('purchases/', include('invoicing.purchase_urls')),
    path('invoice/<int:pk>/post/', views.post_invoice, name='post_invoice'),

    # مسارات POS والبحث التي تسببت في الخطأ
    path('pos/', views.pos_terminal, name='pos_terminal'),
    path('pos/product/', views.product_lookup, name='pos_product_lookup'),
    path('pos/checkout/', views.pos_checkout, name='pos_checkout'),
    path('zatca/', views.zatca_dashboard, name='zatca_dashboard'),
]
