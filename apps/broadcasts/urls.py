from django.urls import path

from . import views

app_name = "broadcasts"

urlpatterns = [
    path("broadcasts/", views.broadcast_list, name="list"),
    path("broadcasts/new/", views.broadcast_create, name="create"),
    path("broadcasts/<int:pk>/", views.broadcast_detail, name="detail"),
    path("broadcasts/<int:pk>/edit/", views.broadcast_edit, name="edit"),
    path("broadcasts/<int:pk>/send/", views.broadcast_send, name="send"),
    path("broadcasts/<int:pk>/cancel/", views.broadcast_cancel, name="cancel"),
    path("availability/", views.availability, name="availability"),
    path("availability/<int:pk>/update/", views.slot_update, name="slot_update"),
    path("waitlist/", views.waitlist, name="waitlist"),
    path("waitlist/<int:pk>/update/", views.waitlist_update, name="waitlist_update"),
    path("settings/richmenu/", views.richmenu, name="richmenu"),
    path("settings/richmenu/preview.png", views.richmenu_preview, name="richmenu_preview"),
]
