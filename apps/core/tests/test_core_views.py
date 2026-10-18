import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import Stylist, User
from apps.customers.models import Customer


@pytest.mark.django_db
def test_signup_creates_stylist_and_redirects_to_onboarding():
    c = Client()
    resp = c.post(
        reverse("accounts:signup"),
        {"name": "新規 美容師", "email": "new@example.com", "password1": "StrongPass#2026", "password2": "StrongPass#2026", "agree": "on"},
    )
    assert resp.status_code == 302
    assert resp.url == reverse("accounts:onboarding_basic")
    user = User.objects.get(email="new@example.com")
    assert Stylist.objects.filter(user=user, display_name="新規 美容師").exists()


@pytest.mark.django_db
def test_today_requires_login():
    resp = Client().get(reverse("core:today"))
    assert resp.status_code == 302
    assert reverse("accounts:login") in resp.url


def test_today_renders(client_logged, customer):
    resp = client_logged.get(reverse("core:today"))
    assert resp.status_code == 200
    assert "今日" in resp.content.decode()


def test_today_redirects_to_onboarding_when_incomplete(client_logged, stylist):
    stylist.onboarding_completed = False
    stylist.save()
    resp = client_logged.get(reverse("core:today"))
    assert resp.status_code == 302
    assert resp.url == reverse("accounts:onboarding_basic")


def test_tenant_isolation_customer_detail(client_logged, other_stylist):
    foreign = Customer.objects.create(stylist=other_stylist, name="他店のお客様")
    resp = client_logged.get(reverse("customers:detail", kwargs={"pk": foreign.pk}))
    assert resp.status_code == 404
    resp = client_logged.get(reverse("customers:list"))
    assert "他店のお客様" not in resp.content.decode()


@pytest.mark.django_db
def test_internal_endpoints_require_token(settings):
    c = Client()
    assert c.post(reverse("core:internal_daily")).status_code == 403
    assert c.get(reverse("core:internal_digest")).status_code == 403
    resp = c.post(reverse("core:internal_daily"), HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN)
    assert resp.status_code == 200
    assert "follow_ups_prepared" in resp.json()
    resp = c.get(reverse("core:internal_digest") + f"?token={settings.INTERNAL_API_TOKEN}")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_pwa_endpoints():
    c = Client()
    assert c.get(reverse("core:manifest")).status_code == 200
    sw = c.get(reverse("core:service_worker"))
    assert sw.status_code == 200
    assert sw["Content-Type"].startswith("application/javascript")
    assert c.get(reverse("core:health")).json() == {"status": "ok"}


def test_static_version_in_pages_and_service_worker(client_logged, settings):
    """CSS/JS の更新がサービスワーカーのキャッシュで止まらない（URL とキャッシュ名にバージョン）"""
    settings.STATIC_VERSION = "12345"
    from django.urls import reverse

    page = client_logged.get(reverse("core:today")).content.decode()
    assert "css/app.css?v=12345" in page and "js/app.js?v=12345" in page
    sw = client_logged.get(reverse("core:service_worker")).content.decode()
    assert 'const CACHE = "tomoni-12345";' in sw and "stale-while-revalidate" in sw

