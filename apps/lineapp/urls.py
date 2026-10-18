from django.urls import path

from . import views

app_name = "lineapp"

urlpatterns = [
    path("line/webhook/<str:key>/", views.webhook, name="webhook"),
    path("r/<str:code>/", views.link_redirect, name="link_redirect"),
    path("settings/line/", views.line_settings, name="settings"),
    path("settings/line/verify/", views.line_verify, name="verify"),
    path("settings/line/quota/", views.line_refresh_quota, name="refresh_quota"),
    path("inbox/", views.inbox, name="inbox"),
    path("inbox/<int:pk>/", views.inbound_detail, name="inbound_detail"),
    path("inbox/<int:pk>/status.json", views.inbound_status, name="inbound_status"),
    path("inbox/<int:pk>/regenerate/", views.inbound_regenerate, name="inbound_regenerate"),
    path("inbox/<int:pk>/ignore/", views.inbound_ignore, name="inbound_ignore"),
    path("inbox/<int:pk>/send/", views.inbound_send, name="inbound_send"),
    path("drafts/<int:pk>/push/", views.draft_push, name="draft_push"),
]
