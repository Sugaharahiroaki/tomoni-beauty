from django.contrib import admin

from .models import Episode, EpisodeUsage, InterviewAnswer, InterviewQuestion, StylistProfile


@admin.register(StylistProfile)
class StylistProfileAdmin(admin.ModelAdmin):
    list_display = ["stylist", "first_person", "emoji_level", "updated_at"]


@admin.register(InterviewQuestion)
class InterviewQuestionAdmin(admin.ModelAdmin):
    list_display = ["order", "text", "theme", "is_active"]
    list_editable = ["is_active"]


@admin.register(InterviewAnswer)
class InterviewAnswerAdmin(admin.ModelAdmin):
    list_display = ["stylist", "question", "status", "updated_at"]
    list_filter = ["status"]


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ["title", "stylist", "source", "is_active", "created_at"]
    list_filter = ["source", "is_active"]
    search_fields = ["title", "body"]


@admin.register(EpisodeUsage)
class EpisodeUsageAdmin(admin.ModelAdmin):
    list_display = ["episode", "sns_post", "used_at"]
