from django.urls import path

from . import views

app_name = "profiles"

urlpatterns = [
    path("interview/", views.interview, name="interview"),
    path("interview/q/<int:order>/", views.interview_question, name="interview_question"),
    path("interview/generate/", views.interview_generate, name="interview_generate"),
    path("settings/style/", views.style_settings, name="style_settings"),
    path("episodes/", views.episode_list, name="episode_list"),
    path("episodes/new/", views.episode_create, name="episode_create"),
    path("episodes/<int:pk>/edit/", views.episode_edit, name="episode_edit"),
    path("episodes/<int:pk>/delete/", views.episode_delete, name="episode_delete"),
    path("episodes/<int:pk>/toggle/", views.episode_toggle, name="episode_toggle"),
]
