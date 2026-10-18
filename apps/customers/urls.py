from django.urls import path

from . import views

app_name = "customers"

urlpatterns = [
    path("customers/", views.customer_list, name="list"),
    path("customers/new/", views.customer_create, name="create"),
    path("customers/search.json", views.customer_search_json, name="search_json"),
    path("customers/<int:pk>/", views.customer_detail, name="detail"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="edit"),
    path("customers/<int:pk>/delete/", views.customer_delete, name="delete"),
    path("customers/<int:pk>/consent/", views.customer_consent, name="consent"),
    path("customers/<int:pk>/link-line/", views.customer_link_line, name="link_line"),
]
