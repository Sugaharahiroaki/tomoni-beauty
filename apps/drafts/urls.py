from django.urls import path

from . import views

app_name = "drafts"

urlpatterns = [
    path("drafts/", views.draft_list, name="list"),
    path("drafts/<int:pk>/", views.draft_detail, name="detail"),
    path("drafts/<int:pk>/update/", views.draft_update, name="update"),
    path("drafts/<int:pk>/reset/", views.draft_reset, name="reset"),
    path("drafts/<int:pk>/sent/", views.draft_mark_sent, name="mark_sent"),
    path("drafts/<int:pk>/discard/", views.draft_discard, name="discard"),
    path("sns/", views.sns_list, name="sns_list"),
    path("sns/new/", views.sns_new, name="sns_new"),
    path("sns/<int:pk>/", views.sns_detail, name="sns_detail"),
    path("sns/<int:pk>/status.json", views.sns_status, name="sns_status"),
    path("sns/<int:pk>/update/", views.sns_update, name="sns_update"),
    path("sns/<int:pk>/posted/", views.sns_mark_posted, name="sns_mark_posted"),
    path("sns/<int:pk>/discard/", views.sns_discard, name="sns_discard"),
    path("sns/<int:pk>/regenerate/", views.sns_regenerate, name="sns_regenerate"),
]
