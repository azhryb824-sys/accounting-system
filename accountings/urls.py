from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from accounts.views import login_view, logout_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    # إضافة مسارات تسجيل الدخول والخروج بالأسماء المطلوبة
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('', include('core.urls')),
    path('invoicing/', include('invoicing.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
