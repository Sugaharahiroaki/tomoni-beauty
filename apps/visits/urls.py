from django.urls import path

from . import views

app_name = "visits"

urlpatterns = [
    path("reservations/", views.reservation_list, name="reservation_list"),
    path("reservations/schedule/", views.schedule, name="schedule"),
    path("reservations/new/", views.reservation_create, name="reservation_create"),
    path("reservations/<int:pk>/edit/", views.reservation_edit, name="reservation_edit"),
    path("reservations/<int:pk>/visited/", views.reservation_visited, name="reservation_visited"),
    path("reservations/<int:pk>/cancel/", views.reservation_cancel, name="reservation_cancel"),
    path("visits/new/", views.visit_create, name="visit_create"),
    path("reservations/emails/", views.reservation_emails, name="reservation_emails"),
    path("reservations/emails/<int:pk>/reparse/", views.reservation_email_reparse, name="reservation_email_reparse"),
    path("reservations/emails/<int:pk>/ignore/", views.reservation_email_ignore, name="reservation_email_ignore"),
    path("reservations/emails/key/", views.reservation_email_key_regenerate, name="reservation_email_key"),
    path("internal/reservations/email/", views.internal_reservation_email, name="internal_reservation_email"),
    path("followups/", views.followup_list, name="followup_list"),
    path("followups/<int:pk>/skip/", views.followup_skip, name="followup_skip"),
    path("followups/<int:pk>/prepare/", views.followup_prepare, name="followup_prepare"),
]
