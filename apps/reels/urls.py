from django.urls import path

from . import connect, views

app_name = "reels"

urlpatterns = [
    path("reels/", views.home, name="home"),
    path("reels/new/", views.start, name="start"),
    path("reels/bulk-delete/", views.bulk_delete_view, name="bulk_delete"),
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
    path("reels/<uuid:pk>/assets/<uuid:asset_id>/role/", views.asset_role, name="asset_role"),
    path("reels/<uuid:pk>/library/add/", views.library_add, name="library_add"),
    path("reels/<uuid:pk>/stock/search.json", views.stock_search, name="stock_search"),
    path("reels/<uuid:pk>/stock/add/", views.stock_add, name="stock_add"),
    path("reels/<uuid:pk>/type/", views.choose_type_view, name="choose_type"),
    path("reels/<uuid:pk>/hooks/", views.choose_hook_view, name="choose_hook"),
    path("reels/<uuid:pk>/hooks/regenerate/", views.hooks_regenerate, name="hooks_regenerate"),
    path("reels/<uuid:pk>/content/regenerate/", views.content_regenerate, name="content_regenerate"),
    path("reels/<uuid:pk>/content/update/", views.content_update, name="content_update"),
    path("reels/<uuid:pk>/content/to-reel/", views.content_to_reel, name="content_to_reel"),
    path("reels/<uuid:pk>/posted/", views.mark_posted_view, name="mark_posted"),
    path("reels/<uuid:pk>/skip/", views.skip_view, name="skip"),
    path("reels/<uuid:pk>/metrics/", views.metrics_update_view, name="metrics_update"),
    path("reels/<uuid:pk>/script/", views.script_generate, name="script_generate"),
    path("reels/<uuid:pk>/script/edit/", views.script_edit, name="script_edit"),
    path("reels/<uuid:pk>/takes/", views.take_upload, name="take_upload"),
    path("reels/<uuid:pk>/render/", views.render_view, name="render"),
    path("reels/<uuid:pk>/schedule/", views.schedule_view, name="schedule"),
    path("reels/<uuid:pk>/cancel-schedule/", views.cancel_schedule_view, name="cancel_schedule"),
    path("reels/<uuid:pk>/delete/", views.delete_view, name="delete"),
]
