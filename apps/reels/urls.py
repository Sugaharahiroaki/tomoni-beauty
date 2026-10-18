from django.urls import path

from . import connect, views

app_name = "reels"

urlpatterns = [
    path("reels/", views.home, name="home"),
    path("reels/new/", views.start, name="start"),
    path("reels/history/", views.history, name="history"),
    path("reels/settings/", views.settings_view, name="settings"),
    path("reels/settings/voice-preview/", views.voice_preview, name="voice_preview"),
    path("reels/connect/<str:platform>/start/", connect.connect_start, name="connect_start"),
    path("reels/connect/<str:platform>/callback/", connect.connect_callback, name="connect_callback"),
    path("reels/connect/<str:platform>/disconnect/", connect.disconnect, name="disconnect"),
    path("reels/<uuid:pk>/", views.workspace, name="workspace"),
    path("reels/<uuid:pk>/status.json", views.status_json, name="status"),
    path("reels/<uuid:pk>/assets/", views.asset_upload, name="asset_upload"),
    path("reels/<uuid:pk>/assets/<uuid:asset_id>/delete/", views.asset_delete, name="asset_delete"),
    path("reels/<uuid:pk>/assets/<uuid:asset_id>/face/", views.asset_face, name="asset_face"),
    path("reels/<uuid:pk>/script/", views.script_generate, name="script_generate"),
    path("reels/<uuid:pk>/script/edit/", views.script_edit, name="script_edit"),
    path("reels/<uuid:pk>/takes/", views.take_upload, name="take_upload"),
    path("reels/<uuid:pk>/render/", views.render_view, name="render"),
    path("reels/<uuid:pk>/schedule/", views.schedule_view, name="schedule"),
    path("reels/<uuid:pk>/cancel-schedule/", views.cancel_schedule_view, name="cancel_schedule"),
    path("reels/<uuid:pk>/delete/", views.delete_view, name="delete"),
]
