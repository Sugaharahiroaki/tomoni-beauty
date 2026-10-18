import pytest
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer
from apps.customers.services import merge_line_shell_into
from apps.lineapp.models import InboundMessage, Message


def test_display_call_name_defaults_to_surname(customer):
    assert customer.display_call_name == "山田さん"
    customer.call_name = "はなちゃん"
    assert customer.display_call_name == "はなちゃん"
    solo = Customer(name="はなこ")
    assert solo.display_call_name == "はなこさん"


def test_consent_toggle_view_records_timestamp(client_logged, customer):
    assert customer.consent_updated_at is None
    resp = client_logged.post(reverse("customers:consent", kwargs={"pk": customer.pk}), {"story_ok": "0", "face_ok": "1"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    customer.refresh_from_db()
    assert customer.story_ok is False and customer.face_ok is True
    assert customer.consent_updated_at is not None


def test_customer_form_sets_tags_and_consent_timestamp(client_logged, stylist):
    resp = client_logged.post(
        reverse("customers:create"),
        {"name": "田中 さくら", "kana": "", "call_name": "", "contact_ok": "on", "photo_ok": "on", "preferred_timing": "平日昼", "memo": "", "tags_text": "カラー, 平日昼"},
    )
    assert resp.status_code == 302
    c = Customer.objects.get(name="田中 さくら", stylist=stylist)
    assert set(c.tags.values_list("name", flat=True)) == {"カラー", "平日昼"}
    assert c.photo_ok is True and c.story_ok is False
    assert c.consent_updated_at is not None


def test_merge_line_shell_moves_messages(stylist, customer):
    shell = Customer.objects.create(stylist=stylist, name="LINEのお客様", line_user_id="Ushell", line_display_name="hana", source=Customer.Source.LINE, needs_review=True, line_followed=True)
    customer.line_user_id = None
    customer.save()
    inbound = InboundMessage.objects.create(stylist=stylist, customer=shell, text="hi", received_at=timezone.now())
    sent = Message.objects.create(stylist=stylist, customer=shell, route=Message.Route.COPY, body="x", sent_at=timezone.now())
    merge_line_shell_into(shell, customer)
    customer.refresh_from_db()
    assert customer.line_user_id == "Ushell" and customer.line_display_name == "hana" and customer.needs_review is False
    assert not Customer.objects.filter(pk=shell.pk).exists()
    inbound.refresh_from_db()
    sent.refresh_from_db()
    assert inbound.customer == customer and sent.customer == customer


def test_merge_rejects_cross_tenant(stylist, other_stylist, customer):
    shell = Customer.objects.create(stylist=other_stylist, name="x", line_user_id="Ux")
    with pytest.raises(ValueError):
        merge_line_shell_into(shell, customer)


def test_delete_customer_cascades(client_logged, stylist, customer):
    InboundMessage.objects.create(stylist=stylist, customer=customer, text="hi", received_at=timezone.now())
    resp = client_logged.post(reverse("customers:delete", kwargs={"pk": customer.pk}))
    assert resp.status_code == 302
    assert not Customer.objects.filter(pk=customer.pk).exists()
    assert not InboundMessage.objects.filter(customer_id=customer.pk).exists()
