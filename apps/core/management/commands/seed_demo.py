"""ローカル確認用のデモデータを投入する。

    python manage.py seed_demo            # demo@example.com / demo1234pass を作り直す

外部APIは呼ばない（AI_FAKE / TRANSCRIPTION_FAKE のダミーで文面を生成）。
"""
import io
from datetime import date, datetime, time, timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import MenuItem, Stylist, User
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


DEMO_PHOTO_DIR = Path(settings.BASE_DIR) / "demo_assets" / "photos"
DEMO_CLIP_DIR = Path(settings.BASE_DIR) / "demo_assets" / "stylist_clips"


def _photo(name: str, fallback_color=(200, 160, 140)) -> SimpleUploadedFile:
    """美容師から提供された実写真（demo_assets/photos/*.jpg）があればそれを、無ければ単色の仮画像を返す"""
    path = DEMO_PHOTO_DIR / f"{name}.jpg"
    if path.exists():
        return SimpleUploadedFile(path.name, path.read_bytes(), content_type="image/jpeg")
    return SimpleUploadedFile(f"{name}.png", _png(fallback_color), content_type="image/png")


class Command(BaseCommand):
    help = "ローカル確認用のデモ美容師アカウントとサンプルデータを作成する"

    def add_arguments(self, parser):
        parser.add_argument("--render", action="store_true", help="見本の動画（SNS動画）をレンダリングまで行う（FFmpeg 必須。GEMINI_API_KEY があればAIの声も入る）")

    @transaction.atomic
    def handle(self, *args, **options):
        User.objects.filter(email=DEMO_EMAIL).delete()
        user = User.objects.create_user(email=DEMO_EMAIL, password=DEMO_PASSWORD, name="佐藤 美咲")
        stylist = Stylist.objects.create(
            user=user,
            display_name="佐藤 美咲",
            salon_name="SOYON なんば店",
            hotpepper_url="https://beauty.hotpepper.jp/slnH000728967/",
            commission_rate=55,  # フリー客
            nominated_commission_rate=65,  # 指名客
            expense_rate=15,  # 歩合から諸経費15%
            salon_access="なんば駅から徒歩1分",
            avg_price=9500,
            weekly_slot_hours=35,
            avg_service_minutes=90,
            onboarding_completed=True,
            interview_completed=True,
        )
        stylist.ensure_email_import_key()
        # メニュー・料金表（SOYON なんば店のホットペッパー掲載より。2026年10月時点）
        menus = [
            ("new", "cut", "【似合わせで垢抜け】ドライカット", 2800, False, "2cm以内のメンテカット。シャンプーなし"),
            ("new", "set", "カット+透明感カラー", 6500, False, ""),
            ("new", "set", "カット+透明感カラー+バイカルテTR", 7500, False, ""),
            ("new", "bleach", "ブリーチ+フルカラー+バイカルテTR", 12900, False, "女性限定"),
            ("new", "bleach", "カット+ブリーチカラー+バイカルテTR（韓国カラー）", 13900, False, "女性限定"),
            ("new", "bleach", "インナーカラー+バイカルテTR", 10900, False, "範囲・色味で変動あり"),
            ("new", "treatment", "【水素髪質改善】アプトグロストリートメント", 6900, False, "カット追加+2,000円"),
            ("repeat", "cut", "ドライカット", 3500, False, "毛先2〜3cm・毛量調整のみ"),
            ("repeat", "color", "ナチュラルカラー", 4200, False, "アディクシーに変更+2,000円"),
            ("repeat", "set", "似合わせカット+ナチュラルカラー", 5900, False, ""),
            ("repeat", "set", "似合わせカット+高発色透明感カラー", 7900, False, "塗り分け+2,000円"),
            ("repeat", "bleach", "リタッチブリーチ+カラー+バイカルテTR", 13500, False, "前回から45日以内・女性限定"),
            ("all", "cut", "シャンプーカット", 4500, False, ""),
            ("all", "color", "カラー", 5000, True, ""),
            ("all", "bleach", "ブリーチカラー", 7000, True, "肩下+1,000円"),
            ("all", "bleach", "ハイライト", 8000, True, ""),
            ("all", "bleach", "バレイヤージュ", 18000, True, ""),
            ("all", "straight", "似合わせカット+縮毛矯正", 11400, False, ""),
            ("all", "treatment", "TOKIOトリートメント", 4000, False, "単品は+1,000円"),
            ("all", "other", "深夜料金", 1000, True, "21時以降は1時間ごとに加算"),
        ]
        for i, (target, category, name, price, price_from, note) in enumerate(menus):
            MenuItem.objects.create(stylist=stylist, target=target, category=category, name=name, price=price, price_from=price_from, note=note, order=i)
        # 所要時間と持ちの目安（SNSのキャプションに使う）
        MenuItem.objects.filter(stylist=stylist, name__contains="透明感カラー").update(minutes=120, duration_weeks=6)
        MenuItem.objects.filter(stylist=stylist, name__contains="ブリーチ").update(minutes=180, duration_weeks=5)
        MenuItem.objects.filter(stylist=stylist, name__contains="縮毛矯正").update(minutes=180, duration_weeks=16)
        MenuItem.objects.filter(stylist=stylist, name__contains="カット", price__lt=5000).update(minutes=45)
        StylistProfile.objects.create(
            stylist=stylist,
            first_person="私",
            tone="やわらかい丁寧語。「〜かなと思います」が多め。押しつけない",
            emoji_level=1,
            area_tags="#なんば美容室, #難波ヘアサロン, #大阪美容室",
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
            display_name="SOYON なんば 佐藤",
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

        karte_today = memo(hanako, today, "今日はカット＋ハイライト。伸びてきたときに根元の境目が目立つのと、色落ちで黄ばむのが気になるとのこと。細めのハイライトで根元をぼかして、アッシュベージュで黄ばみを抑えた。次回は6週間後を目安にリタッチの相談。写真はSNS掲載OK、顔出しはNG。")
        KartePhoto.objects.create(karte=karte_today, image=_photo("highlight_long_back"), sns_ok=True, face_visible=False, role="after", caption="仕上がり（後ろ）")
        KartePhoto.objects.create(karte=karte_today, image=_photo("highlight_bob_back", (150, 120, 110)), sns_ok=True, face_visible=False, role="before", caption="施術前（見本として別の写真）")
        KartePhoto.objects.create(karte=karte_today, image=_photo("highlight_side_hand", (180, 140, 130)), sns_ok=True, face_visible=True, caption="横から（顔あり）")

        karte_due = memo(sakura, today - timedelta(days=40), "カット＋ハイライト。伸びると重く見えるのが悩み。レイヤーを入れて軽さを出した。次回は6週間後。写真も顔出しもOK。")
        KartePhoto.objects.create(karte=karte_due, image=_photo("highlight_medium_back"), sns_ok=True, face_visible=False, caption="仕上がり")
        karte_men = memo(ichiro, today - timedelta(days=10), "メンズカット＋前髪のインナーカラー。襟足が浮きやすい。刈り上げを少し高めに。次回は4週間後。")
        KartePhoto.objects.create(karte=karte_men, image=_photo("mens_orange_bangs"), sns_ok=True, face_visible=True, caption="正面（写真掲載NGのお客様）")
        karte_pink = memo(yui, today - timedelta(days=20), "ブリーチ＋くすみピンク。退色で黄色っぽくなるのが嫌とのこと。ピンクベージュ寄りに調整。次回は5週間後。写真はOK、顔出しはNG。")
        KartePhoto.objects.create(karte=karte_pink, image=_photo("pink_bob_side"), sns_ok=True, face_visible=False, caption="仕上がり（横）")

        # 今日のカルテのお礼は送信済みにして実績を作る
        thanks = Draft.objects.filter(karte=karte_today, kind=Draft.Kind.THANKS_CARE).first()
        if thanks:
            mark_draft_sent(thanks, Message.Route.COPY)
        # 40日前の次回案内は数日前に送った扱い → 予約が入って帰属
        nxt = Draft.objects.filter(karte=karte_due, kind=Draft.Kind.NEXT_VISIT).first()
        if nxt:
            msg = mark_draft_sent(nxt, Message.Route.COPY)
            Message.objects.filter(pk=msg.pk).update(sent_at=timezone.now() - timedelta(days=3))
            r = Reservation.objects.create(stylist=stylist, customer=sakura, reserved_for=timezone.make_aware(datetime.combine(today + timedelta(days=5), time(14, 0))), menu="カット＋ハイライト")
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
        def at(days, hour, minute=0):
            return timezone.make_aware(datetime.combine(today + timedelta(days=days), time(hour, minute)))

        Reservation.objects.create(stylist=stylist, customer=hanako, reserved_for=at(0, 11), menu="カット+透明感カラー")
        Reservation.objects.create(stylist=stylist, customer=yui, reserved_for=at(0, 15), menu="トリートメント")
        Reservation.objects.create(stylist=stylist, customer=None, customer_name_raw="ワタナベ ミキ", reserved_for=at(1, 13), menu="カラー", source=Reservation.Source.EMAIL, note="予約通知メールから取り込み（要確認）")
        Reservation.objects.create(stylist=stylist, customer=ichiro, reserved_for=at(2, 10), menu="ドライカット")
        Reservation.objects.create(stylist=stylist, customer=sakura, reserved_for=at(2, 11, 30), menu="ブリーチ+フルカラー+バイカルテTR")
        AvailabilitySlot.objects.create(stylist=stylist, date=today, start_time=time(17, 0), end_time=time(19, 0), note="夕方")
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
            commission = gross * 55 // 100  # フリー客55%（指名客は65%）
            expenses = commission * 15 // 100  # 歩合から諸経費15%を控除
            st = IncomeStatement.objects.create(
                stylist=stylist, year=y, month=m, salon_name="SOYON なんば店", gross_sales=gross, commission_rate_pct=55, commission_amount=commission,
                deductions=[{"label": "諸経費（歩合の15%）", "amount": expenses}, {"label": "振込手数料", "amount": 440}],
                withholding_tax=0, net_paid=commission - expenses - 440, paid_on=date(y, m, 25) + timedelta(days=15),
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

        # --- SNS動画（リール）: カルテの写真を取り込み、見本の台本まで作っておく ---
        from apps.reels import services as reel_services
        from apps.reels.ai import generate_script as generate_reel_script

        reel_profile = reel_services.profile_of(stylist)
        reel_profile.focus_concerns = ["ブリーチ後の色落ち・黄ばみ", "伸びた根元の境目", "くせ・広がり"]
        reel_profile.purpose = "nomination"
        reel_profile.posts_per_week = 2
        reel_profile.save()

        reel = reel_services.start_post(stylist, post_type="before_after", karte=karte_today, uses_story=True, import_photos=True)
        for name, slot in (("highlight_bob_back", "before"), ("bowl", "bowl"), ("hands", "hands"), ("highlight_medium_back", "after_back")):
            f = _photo(name, (190 + len(slot) * 7, 150, 135))
            reel_services.save_asset(reel, f, f.name, f.content_type, f.size, "photo", slot)
        reel.selected_hook = {"type": "call", "label": "呼びかけ", "text": "伸びた根元の境目が気になる人へ", "visual": "仕上がりの後ろ姿", "hype": []}
        reel.save(update_fields=["selected_hook", "updated_at"])
        generate_reel_script(reel)
        reel_services.start_post(stylist)  # 素材を入れる前のもの

        # 見本の動画（作品集・自己紹介・スタイリストの思い・1日）。素材が demo_assets にあるときだけ作る
        from apps.reels.samples import create_sample_posts

        samples = create_sample_posts(stylist, DEMO_PHOTO_DIR, DEMO_CLIP_DIR, render=options.get("render", False))
        if samples:
            self.stdout.write(f"見本の動画: {len(samples)}本" + ("（レンダリング済み）" if options.get("render") else "（台本まで。--render で動画も作成）"))

        self.stdout.write(self.style.SUCCESS(f"デモアカウントを作成しました: {DEMO_EMAIL} / {DEMO_PASSWORD}"))
