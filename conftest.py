"""pytest 共通フィクスチャ。外部API（Claude / Whisper / LINE）は一切呼ばない。"""
import pytest
from django.test import Client

from apps.accounts.models import Stylist, User
from apps.customers.models import Customer
from apps.lineapp.models import LineChannel
from apps.profiles.models import StylistProfile


@pytest.fixture
def stylist(db) -> Stylist:
    user = User.objects.create_user(email="stylist@example.com", password="pass1234word", name="佐藤 美咲")
    s = Stylist.objects.create(
        user=user,
        display_name="佐藤 美咲",
        salon_name="salon TOMONI",
        hotpepper_url="https://beauty.hotpepper.jp/CSP/bt/reserve/?storeId=H000000001&stylistId=T000000001",
        onboarding_completed=True,
    )
    StylistProfile.objects.create(stylist=s, first_person="私", tone="やわらかい丁寧語", emoji_level=1)
    return s


@pytest.fixture
def other_stylist(db) -> Stylist:
    user = User.objects.create_user(email="other@example.com", password="pass1234word", name="他の美容師")
    return Stylist.objects.create(user=user, display_name="他の美容師", onboarding_completed=True)


@pytest.fixture
def customer(stylist) -> Customer:
    return Customer.objects.create(
        stylist=stylist,
        name="山田 花子",
        kana="やまだ はなこ",
        line_user_id="U0000000000000000000000000000001",
        line_display_name="はなこ",
        line_followed=True,
        contact_ok=True,
        photo_ok=True,
        face_ok=False,
        story_ok=True,
    )


@pytest.fixture
def channel(stylist) -> LineChannel:
    return LineChannel.objects.create(
        stylist=stylist,
        channel_id="1234567890",
        channel_secret="secret-abc",
        channel_access_token="token-xyz",
        bot_user_id="Ubot000000000000000000000000000001",
        basic_id="@tomoni",
        display_name="TOMONI test",
        is_verified=True,
    )


@pytest.fixture
def client_logged(stylist) -> Client:
    c = Client()
    c.force_login(stylist.user)
    return c
