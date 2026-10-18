from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.today, name="today"),
    path("stats/", views.stats, name="stats"),
    path("settings/", views.settings_menu, name="settings_menu"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline, name="offline"),
    path("terms/", views.terms, name="terms"),
    path("privacy/", views.privacy, name="privacy"),
    path("health/", views.health, name="health"),
    path("internal/cron/daily/", views.internal_daily, name="internal_daily"),
    path("internal/digest/", views.internal_digest, name="internal_digest"),
]
