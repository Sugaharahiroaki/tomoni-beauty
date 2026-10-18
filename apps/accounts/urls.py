from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("login/", views.StylistLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("onboarding/basic/", views.onboarding_basic, name="onboarding_basic"),
    path("onboarding/line/", views.onboarding_line, name="onboarding_line"),
    path("onboarding/interview/", views.onboarding_interview, name="onboarding_interview"),
    path("settings/stylist/", views.stylist_settings, name="stylist_settings"),
    path("settings/menus/", views.menu_list, name="menu_list"),
    path("settings/menus/new/", views.menu_edit, name="menu_add"),
    path("settings/menus/bulk/", views.menu_bulk, name="menu_bulk"),
    path("settings/menus/category-minutes/", views.category_minutes_update, name="category_minutes"),
    path("settings/menus/<int:pk>/edit/", views.menu_edit, name="menu_edit"),
    path("settings/menus/<int:pk>/delete/", views.menu_delete, name="menu_delete"),
    path("settings/delete/", views.account_delete, name="account_delete"),
    path("settings/export/", views.export_data, name="export_data"),
]
