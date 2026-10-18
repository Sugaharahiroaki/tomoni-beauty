from django.contrib import admin

from .models import AvailabilitySlot, Broadcast, BroadcastRecipient, RichMenu, WaitlistEntry


class RecipientInline(admin.TabularInline):
    model = BroadcastRecipient
    extra = 0
    readonly_fields = ["customer", "line_user_id", "status", "error", "sent_at"]


@admin.register(Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    list_display = ["title", "stylist", "kind", "status", "target_count", "sent_count", "failed_count", "sent_at"]
    list_filter = ["kind", "status"]
    inlines = [RecipientInline]


@admin.register(AvailabilitySlot)
class AvailabilitySlotAdmin(admin.ModelAdmin):
    list_display = ["stylist", "date", "start_time", "end_time", "status"]


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ["customer", "stylist", "status", "source", "created_at"]


@admin.register(RichMenu)
class RichMenuAdmin(admin.ModelAdmin):
    list_display = ["stylist", "status", "line_rich_menu_id", "published_at"]
