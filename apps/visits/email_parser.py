"""SALON BOARD 等の予約通知メールを解析する（正規表現 → 失敗時は Claude）。

正式なフォーマットは公開されていないため、代表的な表記（「予約日時」「お名前」「メニュー」等のラベル行）を広く拾う。
解析できなければ None を返し、呼び出し側で AI 解析または手入力へフォールバックする。
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

DATE_RE = re.compile(r"(?:(20\d{2})\s*[/年.\-]\s*)?(\d{1,2})\s*[/月.\-]\s*(\d{1,2})\s*日?\s*(?:[（(][月火水木金土日][)）])?\s*(\d{1,2})\s*[:：時]\s*(\d{2})?")
LABEL_PATTERNS = {
    "customer_name": re.compile(r"(?:お客様名|お名前|氏名|ご予約者名?|予約者名?|お客様)\s*[:：]\s*(.+)"),
    "customer_kana": re.compile(r"(?:フリガナ|ふりがな|カナ|よみ)\s*[:：]\s*(.+)"),
    "menu": re.compile(r"(?:メニュー|ご予約メニュー|予約メニュー|コース)\s*[:：]\s*(.+)"),
    "stylist_name": re.compile(r"(?:スタイリスト|担当|指名|担当者)\s*[:：]\s*(.+)"),
    "reservation_id": re.compile(r"(?:予約番号|予約ID|受付番号)\s*[:：]\s*([A-Za-z0-9\-]+)"),
    "reserved_for_line": re.compile(r"(?:来店日時|予約日時|ご来店日時|日時|ご予約日時|予約日)\s*[:：]\s*(.+)"),
}
CANCEL_WORDS = ("キャンセル", "取消", "取り消し", "cancel")
CHANGE_WORDS = ("変更", "日時変更")
KANA_RE = re.compile(r"^[ァ-ヶー\s　]+$")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").replace("　", " ").strip()


def _clean_value(value: str) -> str:
    value = normalize(value)
    value = re.sub(r"\s*(様|さま|さん)$", "", value)
    return value.strip()


def detect_kind(subject: str, body: str) -> str:
    text = f"{subject}\n{body[:400]}"
    if any(w in text for w in CANCEL_WORDS):
        return "cancelled"
    if any(w in text for w in CHANGE_WORDS):
        return "changed"
    if any(w in text for w in ("予約", "ご来店", "受付")):
        return "booked"
    return "unknown"


def parse_datetime(text: str, reference: date | None = None) -> datetime | None:
    """「2026年10月21日（火） 13:00」「10/21 13:00」などを datetime に。年が無ければ reference から推定。"""
    text = normalize(text)
    m = DATE_RE.search(text)
    if not m:
        return None
    year, month, day, hour, minute = m.groups()
    try:
        month_i, day_i, hour_i = int(month), int(day), int(hour)
        minute_i = int(minute) if minute else 0
        if year:
            year_i = int(year)
        else:
            ref = reference or date.today()
            year_i = ref.year
            candidate = date(year_i, month_i, day_i)
            # 受信日より2か月以上前なら翌年扱い（年末に来年の予約が入るケース）
            if (ref - candidate).days > 60:
                year_i += 1
        return datetime(year_i, month_i, day_i, hour_i, minute_i)
    except ValueError:
        return None


def regex_parse(subject: str, body: str, reference: date | None = None) -> dict | None:
    body_n = normalize(body)
    subject_n = normalize(subject)
    out = {"kind": detect_kind(subject_n, body_n), "customer_name": "", "customer_kana": "", "menu": "", "stylist_name": "", "reservation_id": "", "reserved_for": None}

    for key, pattern in LABEL_PATTERNS.items():
        m = pattern.search(body_n)
        if not m:
            continue
        value = _clean_value(m.group(1))
        if key == "reserved_for_line":
            dt = parse_datetime(value, reference)
            if dt:
                out["reserved_for"] = dt.strftime("%Y-%m-%dT%H:%M")
        else:
            out[key] = value

    if not out["reserved_for"]:
        dt = parse_datetime(body_n, reference) or parse_datetime(subject_n, reference)
        if dt:
            out["reserved_for"] = dt.strftime("%Y-%m-%dT%H:%M")

    if out["customer_name"] and not out["customer_kana"] and KANA_RE.match(out["customer_name"]):
        out["customer_kana"] = out["customer_name"]

    if not out["reserved_for"] and not out["customer_name"]:
        return None
    return out


def kana_to_hira(text: str) -> str:
    return "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text)


def name_key(text: str) -> str:
    """氏名比較用のキー（全角半角・空白・カナ/かな の差を吸収）。"""
    return kana_to_hira(normalize(text).replace(" ", "")).lower()
