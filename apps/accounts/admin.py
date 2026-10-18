from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import MenuItem, Stylist, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "name", "is_staff", "is_active", "date_joined"]
    search_fields = ["email", "name"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("個人情報", {"fields": ("name",)}),
        ("権限", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("日時", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "name", "password1", "password2")}),)


@admin.register(Stylist)
class StylistAdmin(admin.ModelAdmin):
    list_display = ["display_name", "salon_name", "user", "onboarding_completed", "interview_completed", "created_at"]
    search_fields = ["display_name", "salon_name", "user__email"]


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ["name", "stylist", "category", "price", "target", "is_active", "order"]
    list_filter = ["category", "target", "is_active"]
    search_fields = ["name", "stylist__display_name"]

