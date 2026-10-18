from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.profiles.urls")),
    path("", include("apps.customers.urls")),
    path("", include("apps.visits.urls")),
    path("", include("apps.karte.urls")),
    path("", include("apps.drafts.urls")),
    path("", include("apps.lineapp.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
