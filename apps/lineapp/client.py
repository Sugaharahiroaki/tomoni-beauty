"""LINE Messaging API の最小クライアント（requests）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class LineApiError(Exception):
    def __init__(self, status_code: int, message: str, payload: dict | None = None):
        super().__init__(f"LINE API {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload or {}


def verify_signature(channel_secret: str, body: bytes, signature: str | None) -> bool:
    """X-Line-Signature（HMAC-SHA256 → base64）を検証する。"""
    if not signature or not channel_secret:
        return False
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


class LineClient:
    def __init__(self, access_token: str, base_url: str | None = None, session: requests.Session | None = None, timeout: float = 10.0):
        self.access_token = access_token
        self.base_url = (base_url or settings.LINE_API_BASE).rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout

    def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        if json is not None:
            headers["Content-Type"] = "application/json"
        try:
            resp = self.session.request(method, f"{self.base_url}{path}", json=json, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise LineApiError(0, f"接続エラー: {exc}") from exc
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except ValueError:
                payload = {"raw": resp.text[:300]}
            message = payload.get("message") or payload.get("raw") or resp.reason
            logger.warning("LINE API error %s %s: %s", method, path, payload)
            raise LineApiError(resp.status_code, message, payload)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    # --- 情報取得 ---
    def get_bot_info(self) -> dict:
        return self._request("GET", "/v2/bot/info")

    def get_profile(self, user_id: str) -> dict:
        return self._request("GET", f"/v2/bot/profile/{user_id}")

    def get_quota(self) -> dict:
        """{"type": "limited", "value": 200} または {"type": "none"}"""
        return self._request("GET", "/v2/bot/message/quota")

    def get_quota_consumption(self) -> dict:
        """{"totalUsage": n}  ※LINE公式アカウントマネージャーからの送信分も含む概算"""
        return self._request("GET", "/v2/bot/message/quota/consumption")

    # --- 送信 ---
    @staticmethod
    def _text_messages(text: str) -> list[dict]:
        # LINE のテキストは1通5000文字まで。超える場合は分割（最大5件）
        chunks = [text[i : i + 4900] for i in range(0, len(text), 4900)] or [""]
        return [{"type": "text", "text": c} for c in chunks[:5]]

    def reply(self, reply_token: str, text: str) -> dict:
        return self._request("POST", "/v2/bot/message/reply", {"replyToken": reply_token, "messages": self._text_messages(text)})

    def push(self, user_id: str, text: str) -> dict:
        return self._request("POST", "/v2/bot/message/push", {"to": user_id, "messages": self._text_messages(text)})
