from django.contrib import admin

from .models import Draft, SnsPost


@admin.register(Draft)
class DraftAdmin(admin.ModelAdmin):
    list_display = ["kind", "customer", "stylist", "status", "scheduled_for", "sent_at", "created_at"]
    list_filter = ["kind", "status"]


@admin.register(SnsPost)
class SnsPostAdmin(admin.ModelAdmin):
    list_display = ["__str__", "stylist", "customer", "uses_story", "episode", "status", "posted_at"]
    list_filter = ["purpose", "status"]
