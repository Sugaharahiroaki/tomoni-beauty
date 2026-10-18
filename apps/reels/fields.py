"""暗号化して保存する文字の項目（SNSの接続トークン用）。

データベースには「enc1:」で始まる暗号文だけが入り、読み出すときに元に戻る。
鍵は環境変数 FIELD_ENCRYPTION_KEY（Fernet の鍵）。未設定なら DJANGO_SECRET_KEY から作る（開発用）。
鍵を変えると読めなくなり空として扱われるので、そのときは接続をやり直してもらう。
"""

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

PREFIX = "enc1:"


@lru_cache(maxsize=1)
def _fernet():
    key = os.getenv("FIELD_ENCRYPTION_KEY")
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()).decode()
    return Fernet(key)


def seal(value):
    if not value or value.startswith(PREFIX):
        return value
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def unseal(value):
    if not value or not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken:
        return ""


class SecretTextField(models.TextField):
    """暗号化して保存する TextField（この項目で検索はしない前提）"""

    def from_db_value(self, value, expression, connection):
        return unseal(value)

    def get_prep_value(self, value):
        return seal(super().get_prep_value(value))
