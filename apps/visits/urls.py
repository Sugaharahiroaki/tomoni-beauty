from django.urls import path

from . import views

app_name = "visits"

urlpatterns = [
    path("reservations/", views.reservation_list, name="reservation_list"),
    path("reservations/new/", views.reservation_create, name="reservation_create"),
    path("reservations/<int:pk>/edit/", views.reservation_edit, name="reservation_edit"),
    path("reservations/<int:pk>/visited/", views.reservation_visited, name="reservation_visited"),
    path("reservations/<int:pk>/cancel/", views.reservation_cancel, name="reservation_cancel"),
    path("visits/new/", views.visit_create, name="visit_create"),
    path("followups/", views.followup_list, name="followup_list"),
    path("followups/<int:pk>/skip/", views.followup_skip, name="followup_skip"),
    path("followups/<int:pk>/prepare/", views.followup_prepare, name="followup_prepare"),
]
