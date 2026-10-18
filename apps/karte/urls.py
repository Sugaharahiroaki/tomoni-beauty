from django.urls import path

from . import views

app_name = "karte"

urlpatterns = [
    path("memos/new/", views.memo_new, name="memo_new"),
    path("memos/", views.memo_create, name="memo_create"),
    path("memos/<int:pk>/", views.memo_detail, name="memo_detail"),
    path("memos/<int:pk>/status.json", views.memo_status, name="memo_status"),
    path("memos/<int:pk>/retry/", views.memo_retry, name="memo_retry"),
    path("karte/", views.karte_list, name="list"),
    path("karte/<int:pk>/", views.karte_detail, name="detail"),
    path("karte/<int:pk>/edit/", views.karte_edit, name="edit"),
    path("karte/<int:pk>/regenerate/", views.karte_regenerate, name="regenerate"),
    path("karte/<int:pk>/delete/", views.karte_delete, name="delete"),
    path("karte/<int:pk>/photos/add/", views.photo_add, name="photo_add"),
    path("photos/<int:pk>/update/", views.photo_update, name="photo_update"),
    path("photos/<int:pk>/delete/", views.photo_delete, name="photo_delete"),
]
