from django.contrib import admin

from .models import Customer, Tag


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "stylist", "line_user_id", "contact_ok", "photo_ok", "face_ok", "story_ok", "needs_review", "created_at"]
    list_filter = ["stylist", "contact_ok", "photo_ok", "story_ok", "needs_review"]
    search_fields = ["name", "kana", "line_display_name"]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name", "stylist"]
