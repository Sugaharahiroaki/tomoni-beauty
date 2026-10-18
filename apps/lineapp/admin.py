from django.contrib import admin

from .models import InboundMessage, LineChannel, LinkClick, Message, QuotaUsage, TrackedLink


@admin.register(LineChannel)
class LineChannelAdmin(admin.ModelAdmin):
    list_display = ["stylist", "basic_id", "display_name", "is_verified", "push_enabled", "last_verified_at"]
    readonly_fields = ["webhook_key", "bot_user_id", "basic_id", "display_name", "last_error"]


@admin.register(InboundMessage)
class InboundMessageAdmin(admin.ModelAdmin):
    list_display = ["customer", "stylist", "message_type", "received_at", "replied_at", "suggestion_status", "needs_attention"]
    list_filter = ["suggestion_status", "needs_attention", "message_type"]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["customer", "stylist", "kind", "route", "status", "sent_at"]
    list_filter = ["route", "kind", "status"]


@admin.register(TrackedLink)
class TrackedLinkAdmin(admin.ModelAdmin):
    list_display = ["code", "stylist", "customer", "kind", "click_count", "created_at"]


@admin.register(LinkClick)
class LinkClickAdmin(admin.ModelAdmin):
    list_display = ["link", "clicked_at"]


@admin.register(QuotaUsage)
class QuotaUsageAdmin(admin.ModelAdmin):
    list_display = ["channel", "year_month", "quota_type", "quota_limit", "total_usage", "local_push_count", "fetched_at"]
