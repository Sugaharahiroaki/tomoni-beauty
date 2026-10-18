"""Claude API クライアント（構造化出力・画像/PDF入力）と、APIキー無しで動くダミー実装。"""
from __future__ import annotations

import base64
import hashlib
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
IMAGE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


class AIError(Exception):
    """文面生成に失敗した。ユーザーに見せられる日本語メッセージを持つ。"""


class AIRefusal(AIError):
    pass


class BaseAIClient:
    def generate_json(self, task: str, system: str, user: str, schema: dict, max_tokens: int = 8000) -> dict:  # pragma: no cover
        raise NotImplementedError

    def generate_json_with_document(self, task: str, system: str, user: str, schema: dict, data: bytes, media_type: str, max_tokens: int = 6000) -> dict:  # pragma: no cover
        raise NotImplementedError


def document_block(data: bytes, media_type: str) -> dict:
    b64 = base64.standard_b64encode(data).decode("utf-8")
    if media_type == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    if media_type in IMAGE_MEDIA_TYPES:
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}
    raise AIError(f"対応していないファイル形式です（{media_type}）。JPEG/PNG/PDF をご利用ください。")


class ClaudeClient(BaseAIClient):
    def __init__(self, model: str | None = None, effort: str | None = None, fallbacks: bool | None = None):
        import anthropic

        self._anthropic = anthropic
        self.model = model or settings.CLAUDE_MODEL
        self.effort = effort or settings.CLAUDE_EFFORT
        self.fallbacks = settings.CLAUDE_FALLBACKS_ENABLED if fallbacks is None else fallbacks
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY or None, timeout=180.0, max_retries=2)

    def _call(self, task: str, system: str, messages: list[dict], schema: dict, max_tokens: int) -> dict:
        a = self._anthropic
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
            "output_config": {"format": {"type": "json_schema", "schema": schema}, "effort": self.effort},
        }
        try:
            if self.fallbacks:
                response = self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                response = self.client.messages.create(**kwargs)
        except a.RateLimitError as exc:
            logger.warning("claude rate limited: %s", exc)
            raise AIError("AIが混み合っています。少し待ってからもう一度お試しください。") from exc
        except a.AuthenticationError as exc:
            raise AIError("Claude APIキーが無効です。管理者に連絡してください。") from exc
        except a.APIStatusError as exc:
            logger.error("claude api error %s: %s", exc.status_code, exc.message)
            raise AIError(f"AIの応答でエラーが発生しました（{exc.status_code}）。") from exc
        except a.APIConnectionError as exc:
            raise AIError("AIサービスに接続できませんでした。通信環境を確認してください。") from exc

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            logger.warning("claude refusal task=%s details=%s", task, details)
            raise AIRefusal("AIがこの内容の生成を見送りました。内容を見直して再度お試しください。")
        if response.stop_reason == "max_tokens":
            raise AIError("生成結果が長すぎて途中で切れました。もう一度お試しください。")

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("claude returned non-json for task=%s: %r", task, text[:500])
            raise AIError("AIの応答を読み取れませんでした。もう一度お試しください。") from exc
        usage = getattr(response, "usage", None)
        if usage is not None:
            logger.info(
                "claude task=%s model=%s in=%s out=%s cache_read=%s",
                task,
                getattr(response, "model", self.model),
                getattr(usage, "input_tokens", None),
                getattr(usage, "output_tokens", None),
                getattr(usage, "cache_read_input_tokens", None),
            )
        return data

    def generate_json(self, task: str, system: str, user: str, schema: dict, max_tokens: int = 8000) -> dict:
        return self._call(task, system, [{"role": "user", "content": user}], schema, max_tokens)

    def generate_json_with_document(self, task: str, system: str, user: str, schema: dict, data: bytes, media_type: str, max_tokens: int = 6000) -> dict:
        content = [document_block(data, media_type), {"type": "text", "text": user}]
        return self._call(task, system, [{"role": "user", "content": content}], schema, max_tokens)


class FakeAIClient(BaseAIClient):
    """APIキー無しの開発・テスト用。入力に応じたそれらしい日本語を返す。"""

    def generate_json(self, task: str, system: str, user: str, schema: dict, max_tokens: int = 8000) -> dict:
        handler = getattr(self, f"_task_{task}", None)
        if handler is None:
            raise AIError(f"FakeAIClient: 未対応タスク {task}")
        return handler(user)

    def generate_json_with_document(self, task: str, system: str, user: str, schema: dict, data: bytes, media_type: str, max_tokens: int = 6000) -> dict:
        document_block(data, media_type)  # 形式チェックだけ本物と同じにする
        return self.generate_json(task, system, user, schema, max_tokens)

    @staticmethod
    def _seed(user: str) -> int:
        return int(hashlib.sha256(user.encode("utf-8")).hexdigest()[:8], 16)

    def _task_karte(self, user: str) -> dict:
        transcript = user.split("【文字起こし】", 1)[-1].strip()
        has_photo_ok = "掲載OK" in transcript or "掲載ok" in transcript.lower()
        face_ng = "顔出しNG" in transcript or "顔出しはNG" in transcript or "顔出しなし" in transcript
        return {
            "treatment_summary": "落ち着いたブラウン系のカラーで、褪色時に赤みが出にくいよう調整。",
            "menu_items": ["カラー"],
            "design_details": "暗めのブラウン。マット寄りに補色を入れて赤みを抑えた配合。",
            "concerns": ["色落ちが早く、すぐ明るくなってしまう"],
            "results": "褪色しても赤みが出にくい設計にし、持ちを重視した色味に。",
            "products_used": [],
            "home_care_advice": ["カラーシャンプーを週2回", "ドライヤー前にアウトバストリートメント"],
            "next_check_items": ["色落ちの進み方", "赤みの出方"],
            "next_visit_weeks": 6,
            "customer_requests": ["次回はリタッチを相談"],
            "permission_mentions": {"photo_ok": True if has_photo_ok else None, "face_ok": False if face_ng else None, "story_ok": None},
            "private_notes": "（ダミー）会話メモ: 特になし。元の文字起こし: " + transcript[:80],
        }

    def _task_drafts(self, user: str) -> dict:
        has_link = "予約リンク: あり" in user
        link_line = "\nご予約はこちらから👇\n{予約リンク}" if has_link else ""
        return {
            "thanks_care": (
                "{お名前}、本日はご来店ありがとうございました✨\n\n"
                "今日は褪色しても赤みが出にくいブラウンに仕上げました。\n"
                "・カラーシャンプーは週2回くらいがおすすめです\n"
                "・乾かす前にアウトバストリートメントを毛先に\n"
                "・38℃くらいのぬるめのお湯で洗うと色持ちが良くなります\n\n"
                "気になることがあれば、このLINEにいつでもご連絡ください😊\n"
                "次回は6週間後くらいが目安です。" + link_line
            ),
            "next_visit": (
                "{お名前}、こんにちは！前回のカラーから1か月ほど経ちましたが、色味はいかがですか？\n"
                "根元が気になりはじめる頃かなと思い、ご連絡しました。\n"
                "次回はリタッチ＋毛先のトリートメントがおすすめです。" + link_line + "\nご都合の良いタイミングでどうぞ🍀"
            ),
        }

    def _task_generalize(self, user: str) -> dict:
        return {
            "concern": "カラーの色落ちが早く、毎回すぐに明るくなってしまう",
            "result": "落ち着いたブラウンで、褪色しても赤みが出にくい設計にしました",
            "removed_items": [],
        }

    def _task_sns(self, user: str) -> dict:
        n = self._seed(user) % 3
        openers = ["「色落ちが早くて、すぐ明るくなっちゃう」", "褪色まで考えてカラーを選ぶ、という話。", "今日のカラーは、1か月後の自分のためのカラー。"]
        return {
            "feed_text": (
                f"{openers[n]}\n\n"
                "そんなご相談から、今日は落ち着いたブラウンに。\n"
                "褪色しても赤みが出にくいように補色を入れて、持ちを一番に考えた配合にしました。\n\n"
                "私がカラーで一番大事にしているのは「染めた日」より「3週間後」。\n"
                "修業時代、毎回色落ちにがっかりしているお客様を見て、落ち着いた色こそ設計が大事だと教わりました。\n\n"
                "平日の昼は落ち着いてご案内できます。色落ちのお悩み、ぜひご相談ください。"
            ),
            "story_text": "色落ちが早い人へ。褪色しても赤みが出にくいブラウン、仕込みました🤎",
            "reel_script": (
                "[0-3秒] テロップ:「色落ち、早くない？」\n"
                "[3-8秒] 施術前→後の寄り。ナレ: 今日は褪色まで考えたブラウン。\n"
                "[8-15秒] ナレ: 赤みが出ないように補色をひとさじ。\n"
                "[15-22秒] ナレ: 私が大事にしてるのは、染めた日より3週間後。\n"
                "[22-28秒] テロップ: 色落ちの悩み、DMで相談してね"
            ),
            "hashtags": ["#ブラウンカラー", "#色落ち対策", "#暗髪カラー", "#透明感カラー", "#大人カラー", "#髪質改善", "#美容師", "#フリーランス美容師", "#ヘアカラー", "#カラー相談"],
        }

    def _task_pii_check(self, user: str) -> dict:
        return {"has_pii": False, "findings": []}

    def _task_episodes(self, user: str) -> dict:
        return {
            "episodes": [
                {
                    "title": "母の髪を切った日",
                    "body": "美容師になろうと思ったきっかけは、中学生の頃に母の髪を切ったことでした。上手ではなかったけれど、鏡を見て笑ってくれた顔が忘れられなくて。今も「鏡を見た瞬間の表情」を一番の判断基準にしています。",
                    "themes": ["きっかけ", "価値観", "カウンセリング"],
                    "question_order": 1,
                },
                {
                    "title": "3週間後を考えるようになった修業時代",
                    "body": "アシスタント時代、色落ちにがっかりして戻ってくるお客様を何人も見ました。あの経験から、染めた日の仕上がりより3週間後の髪を想像して配合するようになりました。",
                    "themes": ["カラー", "色落ち", "修業時代", "丁寧さ"],
                    "question_order": 2,
                },
                {
                    "title": "休日は植物の手入れ",
                    "body": "休みの日はベランダの植物を手入れしています。毎日少しずつ変わっていくのを見るのが好きで、髪も同じだなと思います。急がず、続けられるケアを一緒に考えたいです。",
                    "themes": ["休日", "価値観", "ホームケア"],
                    "question_order": 10,
                },
            ],
            "style_summary": "やわらかい丁寧語。「〜かなと思います」「〜してみてください」など押しつけない語尾。絵文字は控えめ。",
            "suggested_first_person": "私",
        }

    def _task_reply(self, user: str) -> dict:
        text = user.split("【お客様からのメッセージ】", 1)[-1]
        if any(k in text for k in ("予約", "空いて", "いつ")):
            intent = "reservation"
            body = "ご連絡ありがとうございます😊 ご希望の日時をいくつか教えていただけますか？確認してお返事します。{予約リンク}"
        elif "キャンセル" in text:
            intent = "cancel"
            body = "ご連絡ありがとうございます。承知しました、お気遣いなく！またご都合の良いときにお待ちしています。"
        else:
            intent = "question"
            body = "ご連絡ありがとうございます😊 確認してお返事しますので、少しお待ちください。"
        return {"reply_text": body, "intent": intent, "needs_attention": "痛" in text or "かゆ" in text, "note_for_stylist": ""}

    def _task_broadcast(self, user: str) -> dict:
        has_link = "予約リンク: あり" in user
        link = "\n{予約リンク}" if has_link else ""
        if "【kind】availability" in user or "【kind】waitlist" in user:
            slots = user.split("【空き枠】", 1)[-1].split("【伝えたい内容", 1)[0].strip()
            body = "こんにちは！直近でご案内できる空き枠が出ました🍀\n\n" + (slots or "・ご希望の日時をご相談ください") + "\n\n気になる方はこのLINEかこちらからどうぞ。" + link
        elif "【kind】segment" in user:
            body = "こんにちは！前回のご来店から少し時間が経ちましたが、髪の調子はいかがですか？\n根元や毛先が気になりはじめる頃かなと思いご連絡しました。\nご都合の良いときにお待ちしています🍀" + link
        else:
            notes = user.split("【伝えたい内容（美容師のメモ）】", 1)[-1].strip()
            body = "いつもありがとうございます！お知らせです。\n\n" + (notes if notes and notes != "（指定なし）" else "来月の営業日とおすすめメニューのご案内です。") + "\n\nご予約・ご相談はこのLINEからいつでもどうぞ😊" + link
        return {
            "body": body,
            "free_alternatives": [
                "リッチメニューの「予約する」ボタン横に空き状況のテキストを追加して更新する（通数0）",
                "あいさつメッセージに今月の空き枠を載せる（新しく友だち追加した人に届く・通数0）",
                "LINE VOOM と Instagram ストーリーズに同じ内容を投稿する（通数0）",
            ],
        }

    def _task_ocr_receipt(self, user: str) -> dict:
        return {
            "date": "2026-10-15",
            "vendor": "ビューティーガレージ 渋谷店",
            "total": 6820,
            "tax": 620,
            "items": [{"name": "カラー剤 ブラウン系 2本", "amount": 4400}, {"name": "ニトリル手袋 100枚", "amount": 1800}],
            "suggested_category": "materials",
            "payment_hint": "card",
            "confidence": "medium",
            "notes": "（ダミーOCR）手袋は消耗品費に分ける判断もあります。",
        }

    def _task_ocr_statement(self, user: str) -> dict:
        return {
            "period_year": 2026,
            "period_month": 9,
            "salon_name": "salon TOMONI",
            "gross_sales": 420000,
            "commission_rate_pct": 50,
            "commission_amount": 210000,
            "deductions": [{"label": "材料費", "amount": 21000}, {"label": "振込手数料", "amount": 440}],
            "withholding_tax": 0,
            "net_paid": 188560,
            "paid_on": "2026-10-10",
            "confidence": "medium",
            "notes": "（ダミーOCR）",
        }

    def _task_reservation_email(self, user: str) -> dict:
        from apps.visits.email_parser import regex_parse

        subject = user.split("【件名】", 1)[-1].split("\n", 1)[0].strip() if "【件名】" in user else ""
        body = user.split("【本文】", 1)[-1] if "【本文】" in user else user
        parsed = regex_parse(subject, body) or {}
        return {
            "kind": parsed.get("kind") or "unknown",
            "customer_name": parsed.get("customer_name", ""),
            "customer_kana": parsed.get("customer_kana", ""),
            "reserved_for": parsed.get("reserved_for"),
            "menu": parsed.get("menu", ""),
            "stylist_name": parsed.get("stylist_name", ""),
            "reservation_id": parsed.get("reservation_id", ""),
            "confidence": "medium" if parsed.get("reserved_for") else "low",
        }


_client: BaseAIClient | None = None


def get_ai() -> BaseAIClient:
    global _client
    if _client is None:
        _client = FakeAIClient() if settings.AI_FAKE else ClaudeClient()
    return _client


def reset_ai():
    global _client
    _client = None
