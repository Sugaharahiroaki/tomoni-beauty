from django.contrib import admin

from .models import Karte, KartePhoto, VoiceMemo


@admin.register(VoiceMemo)
class VoiceMemoAdmin(admin.ModelAdmin):
    list_display = ["customer", "stylist", "visited_on", "status", "created_at"]
    list_filter = ["status"]


class KartePhotoInline(admin.TabularInline):
    model = KartePhoto
    extra = 0


@admin.register(Karte)
class KarteAdmin(admin.ModelAdmin):
    list_display = ["customer", "stylist", "visited_on", "menu_display", "next_visit_weeks"]
    inlines = [KartePhotoInline]
