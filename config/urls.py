from django.contrib import admin
from django.urls import include, path, re_path

from apps.core.media_access import serve_media

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
    path("", include("apps.broadcasts.urls")),
    path("", include("apps.reels.urls")),
    path("money/", include("apps.ledger.urls")),
    # 写真・動画・音声は見てよい人にだけ渡す（本番は Nginx の X-Accel-Redirect で送り出す）
    re_path(r"^media/(?P<path>.+)$", serve_media, name="media"),
]
