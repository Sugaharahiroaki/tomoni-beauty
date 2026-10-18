"""ローカル確認用のデモデータを投入する。

    python manage.py seed_demo            # demo@example.com / demo1234pass を作り直す

外部APIは呼ばない（AI_FAKE / TRANSCRIPTION_FAKE のダミーで文面を生成）。
"""
import io
from datetime import date, time, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Stylist, User
from apps.broadcasts.models import AvailabilitySlot, Broadcast, WaitlistEntry
from apps.core.dates import today_local
from apps.customers.models import Customer, Tag
from apps.drafts.models import Draft, SnsPost
from apps.drafts.services import generate_sns_post, mark_draft_sent
from apps.karte.models import KartePhoto, VoiceMemo
from apps.karte.services import process_voice_memo
from apps.ledger.models import Expense, FilingProfile, IncomeStatement, OpeningBalance, OtherIncome, Receipt
from apps.ledger.ocr import run_receipt_ocr
from apps.ledger.services import confirm_statement, get_tax_settings
from apps.lineapp.models import InboundMessage, LineChannel, Message, QuotaUsage
from apps.lineapp.services import suggest_reply_for_inbound
from apps.profiles.models import Episode, InterviewAnswer, InterviewQuestion, StylistProfile
from apps.visits.models import Reservation, Visit
from apps.visits.services import attribute_reservation

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo1234pass"


def _png(color=(200, 160, 140), size=(600, 800)) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, color)
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, size[0] - 40, size[1] - 40], outline=(255, 255, 255), width=6)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class Command(BaseCommand):
    help = "ローカル確認用のデモ美容師アカウントとサンプルデータを作成する"

    @transaction.atomic
    def handle(self, *args, **options):
        User.objects.filter(email=DEMO_EMAIL).delete()
        user = User.objects.create_user(email=DEMO_EMAIL, password=DEMO_PASSWORD, name="佐藤 美咲")
        stylist = Stylist.objects.create(
            user=user,
            display_name="佐藤 美咲",
            salon_name="salon TOMONI 表参道",
            hotpepper_url="https://beauty.hotpepper.jp/CSP/bt/reserve/?storeId=H000000001&stylistId=T000000001",
            commission_rate=50,
            avg_price=8800,
            weekly_slot_hours=35,
            avg_service_minutes=90,
            onboarding_completed=True,
            interview_completed=True,
        )
        stylist.ensure_email_import_key()
        StylistProfile.objects.create(
            stylist=stylist,
            first_person="私",
            tone="やわらかい丁寧語。「〜かなと思います」が多め。押しつけない",
            emoji_level=1,
            area_tags="#表参道美容室, #渋谷ヘアサロン",
            style_summary="落ち着いた口調で、専門用語は噛み砕いて説明する。語尾は「〜です」「〜してみてください」。",
        )
        for q in InterviewQuestion.objects.filter(order__lte=4):
            InterviewAnswer.objects.create(stylist=stylist, question=q, transcript=f"（デモ回答）Q{q.order} についての話。", status=InterviewAnswer.Status.DONE)
        Episode.objects.create(stylist=stylist, title="母の髪を切った日", body="美容師になろうと思ったきっかけは、中学生の頃に母の髪を切ったことでした。鏡を見て笑ってくれた顔が忘れられなくて、今も「鏡を見た瞬間の表情」を一番の判断基準にしています。", themes=["きっかけ", "価値観", "カウンセリング"], source=Episode.Source.AI)
        Episode.objects.create(stylist=stylist, title="3週間後を考えるようになった修業時代", body="アシスタント時代、色落ちにがっかりして戻ってくるお客様を何人も見ました。あの経験から、染めた日の仕上がりより3週間後の髪を想像して配合するようになりました。", themes=["カラー", "色落ち", "修業時代", "丁寧さ"], source=Episode.Source.AI)
        Episode.objects.create(stylist=stylist, title="初めての方には必ず聞くこと", body="初めての方には「今まで一番よかった髪型」と「一番困った髪型」を必ず聞きます。やりたいことより、やりたくないことの方が本音が出るからです。", themes=["初めての方", "カウンセリング", "接客"], source=Episode.Source.AI)

        channel = LineChannel.objects.create(
            stylist=stylist,
            channel_id="1650000000",
            channel_secret="demo-secret-not-real",
            channel_access_token="demo-token-not-real",
            bot_user_id="Udemo0000000000000000000000000bot",
            basic_id="@tomoni-demo",
            display_name="salon TOMONI 佐藤",
            is_verified=True,
            last_verified_at=timezone.now(),
        )
        QuotaUsage.objects.create(channel=channel, year_month=today_local().strftime("%Y-%m"), quota_type="limited", quota_limit=200, total_usage=37)

        tag_color, _ = Tag.objects.get_or_create(stylist=stylist, name="カラー")
        tag_weekday, _ = Tag.objects.get_or_create(stylist=stylist, name="平日昼")
        tag_regular, _ = Tag.objects.get_or_create(stylist=stylist, name="常連")

        def customer(name, kana, line=True, **kw):
            c = Customer.objects.create(
                stylist=stylist,
                name=name,
                kana=kana,
                line_user_id=f"Udemo{abs(hash(name)) % 10**26:026d}" if line else None,
                line_display_name=kana.split()[-1] if line else "",
                line_followed=line,
                consent_updated_at=timezone.now(),
                **kw,
            )
            return c

        hanako = customer("山田 花子", "やまだ はなこ", photo_ok=True, face_ok=False, story_ok=True, preferred_timing="平日昼")
        hanako.tags.add(tag_color, tag_weekday, tag_regular)
        ichiro = customer("鈴木 一郎", "すずき いちろう", photo_ok=False, story_ok=False)
        sakura = customer("田中 さくら", "たなか さくら", photo_ok=True, face_ok=True, story_ok=True, preferred_timing="土曜午前")
        sakura.tags.add(tag_color)
        yui = customer("高橋 結衣", "たかはし ゆい", line=False, photo_ok=True, story_ok=False)
        kenta = customer("伊藤 健太", "いとう けんた", contact_ok=False)
        shell = Customer.objects.create(stylist=stylist, name="はな", line_user_id="Udemo_shell_000000000000000000000", line_display_name="はな", line_followed=True, source=Customer.Source.LINE, needs_review=True)

        today = today_local()

        # --- 来店とカルテ（音声メモはテキスト入力で代替） ---
        def memo(cust, visited_on, text):
            m = VoiceMemo.objects.create(stylist=stylist, customer=cust, visited_on=visited_on, text_input=text)
            process_voice_memo(m.id)
            m.refresh_from_db()
            return m.karte

        karte_today = memo(hanako, today, "今日は落ち着いたブラウンにカラー。色落ちが早くて毎回すぐ明るくなるのが気になるとのこと。赤みが出にくいようにマット寄りに調整。次回は6週間後を目安にリタッチの相談。写真はSNS掲載OK、顔出しはNG。")
        KartePhoto.objects.create(karte=karte_today, image=SimpleUploadedFile("after.png", _png(), content_type="image/png"), sns_ok=True, face_visible=False, caption="仕上がり")
        KartePhoto.objects.create(karte=karte_today, image=SimpleUploadedFile("face.png", _png((180, 140, 130)), content_type="image/png"), sns_ok=True, face_visible=True, caption="正面")

        karte_due = memo(sakura, today - timedelta(days=40), "カット＋ハイライト。伸びると重く見えるのが悩み。レイヤーを入れて軽さを出した。次回は6週間後。写真も顔出しもOK。")
        memo(ichiro, today - timedelta(days=10), "メンズカット。襟足が浮きやすい。刈り上げを少し高めに。次回は4週間後。")

        # 今日のカルテのお礼は送信済みにして実績を作る
        thanks = Draft.objects.filter(karte=karte_today, kind=Draft.Kind.THANKS_CARE).first()
        if thanks:
            mark_draft_sent(thanks, Message.Route.COPY)
        # 40日前の次回案内は数日前に送った扱い → 予約が入って帰属
        nxt = Draft.objects.filter(karte=karte_due, kind=Draft.Kind.NEXT_VISIT).first()
        if nxt:
            msg = mark_draft_sent(nxt, Message.Route.COPY)
            Message.objects.filter(pk=msg.pk).update(sent_at=timezone.now() - timedelta(days=3))
            r = Reservation.objects.create(stylist=stylist, customer=sakura, reserved_for=timezone.now() + timedelta(days=5, hours=3), menu="カット＋ハイライト")
            attribute_reservation(r)

        # SNS投稿
        post = SnsPost.objects.create(stylist=stylist, customer=hanako, karte=karte_today, purpose=SnsPost.Purpose.NOMINATION, uses_story=True, episode=Episode.objects.filter(stylist=stylist, title__contains="3週間後").first())
        post.photos.set([p for p in karte_today.photos.all() if p.usable_for_sns()])
        generate_sns_post(post.id)

        # --- LINE受信 ---
        inbound = InboundMessage.objects.create(stylist=stylist, customer=ichiro, text="来週の土曜って午後空いてますか？カットお願いしたいです", reply_token="demo-reply-token", received_at=timezone.now() - timedelta(minutes=2), line_message_id="demo-1")
        suggest_reply_for_inbound(inbound.id)
        old = InboundMessage.objects.create(stylist=stylist, customer=hanako, text="昨日はありがとうございました！色味すごく気に入りました。カラーシャンプーって何がいいですか？", reply_token="demo-old", received_at=timezone.now() - timedelta(hours=5), line_message_id="demo-2")
        suggest_reply_for_inbound(old.id)
        InboundMessage.objects.create(stylist=stylist, customer=shell, text="はじめまして！予約したいです", reply_token="", received_at=timezone.now() - timedelta(days=1), line_message_id="demo-3", suggestion_status=InboundMessage.SuggestionStatus.NONE)

        # --- 予約・来店 ---
        Reservation.objects.create(stylist=stylist, customer=yui, reserved_for=timezone.now().replace(hour=15, minute=0, second=0, microsecond=0), menu="トリートメント")
        Reservation.objects.create(stylist=stylist, customer=None, customer_name_raw="ワタナベ ミキ", reserved_for=timezone.now() + timedelta(days=2), menu="カラー", source=Reservation.Source.EMAIL, note="予約通知メールから取り込み（要確認）")
        past = Reservation.objects.create(stylist=stylist, customer=ichiro, reserved_for=timezone.now() - timedelta(days=10), menu="カット", status=Reservation.Status.VISITED)
        Visit.objects.create(stylist=stylist, customer=ichiro, visited_at=past.reserved_for, menu="カット", price=5500, duration_minutes=60, reservation=past)

        # --- 配信・空き枠・キャンセル待ち ---
        Broadcast.objects.create(stylist=stylist, kind=Broadcast.Kind.ANNOUNCEMENT, title="10月の営業日とお知らせ", body="（デモ）10月は毎週火曜が定休日です。", status=Broadcast.Status.SENT, sent_at=timezone.now() - timedelta(days=20), target_count=42, planned_messages=42, sent_count=42, quota_limit_snapshot=200, quota_used_snapshot=0)
        Broadcast.objects.create(stylist=stylist, kind=Broadcast.Kind.SEGMENT, title="最終来店から2か月以上の方へ", body="こんにちは！前回のご来店から少し経ちましたが、髪の調子はいかがですか？\n根元や毛先が気になりはじめる頃かなと思いご連絡しました。\n{予約リンク}", segment={"last_visit_min_days": 60, "exclude_recent_days": 30, "exclude_reserved": True, "tags": [], "include_never_visited": False, "preferred_timing": "", "menu_keyword": "", "waitlist_only": False})
        week_start = today - timedelta(days=today.weekday())
        for offset, start, end in ((1, time(13, 0), time(16, 0)), (3, time(10, 0), time(12, 0)), (5, time(14, 0), time(17, 0))):
            d = week_start + timedelta(days=offset)
            if d >= today:
                AvailabilitySlot.objects.create(stylist=stylist, date=d, start_time=start, end_time=end)
        AvailabilitySlot.objects.create(stylist=stylist, date=today + timedelta(days=8), start_time=time(11, 0), end_time=time(14, 0), note="平日昼")
        WaitlistEntry.objects.create(stylist=stylist, customer=hanako, source=WaitlistEntry.Source.RICHMENU, preferred_timing="平日昼")
        WaitlistEntry.objects.create(stylist=stylist, customer=sakura, source=WaitlistEntry.Source.MANUAL, note="土曜の午前希望")

        # --- お金 ---
        year = today.year
        OpeningBalance.objects.create(stylist=stylist, year=year, cash=30000, bank=250000, receivable=0)
        get_tax_settings(stylist)
        for i in range(3, 0, -1):
            m = today.month - i
            y = year
            if m <= 0:
                m += 12
                y -= 1
            gross = 400000 + i * 15000
            st = IncomeStatement.objects.create(
                stylist=stylist, year=y, month=m, salon_name="salon TOMONI 表参道", gross_sales=gross, commission_rate_pct=50, commission_amount=gross // 2,
                deductions=[{"label": "材料費", "amount": gross // 20}, {"label": "振込手数料", "amount": 440}],
                withholding_tax=0, net_paid=gross // 2 - gross // 20 - 440, paid_on=date(y, m, 25) + timedelta(days=15),
            )
            confirm_statement(st)
        samples = [
            (today - timedelta(days=3), 3280, "supplies", "ドラッグストア", "タオル・手袋", Expense.Payment.PRIVATE, 100),
            (today - timedelta(days=9), 12000, "training", "カラーセミナー", "受講料", Expense.Payment.BANK, 100),
            (today - timedelta(days=15), 8800, "communication", "携帯キャリア", "スマホ代", Expense.Payment.PRIVATE, 50),
            (today - timedelta(days=20), 1240, "travel", "交通系IC", "講習会への移動", Expense.Payment.CASH, 100),
            (today - timedelta(days=33), 5500, "advertising", "印刷", "名刺", Expense.Payment.PRIVATE, 100),
            (today - timedelta(days=50), 16500, "materials", "ビューティーガレージ", "カラー剤", Expense.Payment.PRIVATE, 100),
        ]
        for d, amount, cat, vendor, desc, pay, ratio in samples:
            Expense.objects.create(stylist=stylist, date=d, amount=amount, category=cat, vendor=vendor, description=desc, payment_method=pay, business_ratio=ratio, status=Expense.Status.CONFIRMED)
        OtherIncome.objects.create(stylist=stylist, date=today - timedelta(days=12), amount=6600, description="ホームケア商品の販売", received_to=OtherIncome.ReceivedTo.CASH)
        receipt = Receipt.objects.create(stylist=stylist, file=SimpleUploadedFile("receipt.png", _png((245, 245, 240), (480, 800)), content_type="image/png"))
        run_receipt_ocr(receipt.id)
        FilingProfile.objects.create(stylist=stylist, full_name="佐藤 美咲", full_name_kana="サトウ ミサキ", address="東京都渋谷区神宮前1-1-1", tax_office="渋谷", business_name="", opened_on=date(year, 4, 1), bookkeeping=FilingProfile.Bookkeeping.SIMPLE, books=["現金出納帳", "売掛帳", "経費帳"], start_blue_year=year)

        self.stdout.write(self.style.SUCCESS(f"デモアカウントを作成しました: {DEMO_EMAIL} / {DEMO_PASSWORD}"))
