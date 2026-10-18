from django.contrib import admin

from .models import FollowUp, Reservation, Visit


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ["__str__", "stylist", "status", "source", "attributed_message", "created_at"]
    list_filter = ["status", "source"]


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ["customer", "stylist", "visited_at", "menu", "price"]


@admin.register(FollowUp)
class FollowUpAdmin(admin.ModelAdmin):
    list_display = ["customer", "stylist", "kind", "due_date", "status"]
    list_filter = ["status", "kind"]
