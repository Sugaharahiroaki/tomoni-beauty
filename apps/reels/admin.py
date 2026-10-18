from django.contrib import admin

from .models import BgmTrack, MediaAsset, PostMetric, ReelPost, ReelProfile, RenderJob, ShotExample, UsageLog


@admin.register(ReelProfile)
class ReelProfileAdmin(admin.ModelAdmin):
    list_display = ["stylist", "brand_name", "narration_mode", "voice_name", "post_to_instagram", "post_to_youtube", "post_to_threads"]
    readonly_fields = ["instagram_access_token", "youtube_refresh_token", "threads_access_token"]


class AssetInline(admin.TabularInline):
    model = MediaAsset
    extra = 0
    fields = ["kind", "slot", "face_visible", "source", "duration_sec", "taken_at"]
    readonly_fields = ["kind", "duration_sec", "taken_at"]


class RenderJobInline(admin.TabularInline):
    model = RenderJob
    extra = 0
    readonly_fields = ["status", "attempts", "error", "started_at", "finished_at"]


@admin.register(ReelPost)
class ReelPostAdmin(admin.ModelAdmin):
    list_display = ["theme_title", "stylist", "template_key", "status", "scheduled_at", "published_at", "created_at"]
    list_filter = ["status", "template_key"]
    inlines = [AssetInline, RenderJobInline]


@admin.register(BgmTrack)
class BgmTrackAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "mood", "duration_sec", "license_confirmed", "active", "used_count"]
    list_editable = ["license_confirmed", "active"]
    list_filter = ["category", "license_confirmed"]


@admin.register(ShotExample)
class ShotExampleAdmin(admin.ModelAdmin):
    list_display = ["template_key", "slot_key", "note", "active"]


@admin.register(PostMetric)
class PostMetricAdmin(admin.ModelAdmin):
    list_display = ["post", "platform", "views", "likes", "saves", "fetched_at"]


@admin.register(UsageLog)
class UsageLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "stylist", "provider", "operation", "cost_usd"]
