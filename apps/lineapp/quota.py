"""通数（メッセージクォータ）の純粋計算。テスト対象。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuotaStatus:
    limit: int | None  # None = 上限なし（従量課金プラン）
    used: int
    planned: int = 0

    @property
    def remaining(self) -> int | None:
        if self.limit is None:
            return None
        return max(self.limit - self.used, 0)

    @property
    def remaining_after(self) -> int | None:
        if self.limit is None:
            return None
        return self.limit - self.used - self.planned

    @property
    def would_exceed(self) -> bool:
        return self.limit is not None and (self.used + self.planned) > self.limit

    @property
    def ratio(self) -> float:
        if not self.limit:
            return 0.0
        return min((self.used + self.planned) / self.limit, 1.0)

    def warn(self, warn_ratio: float = 0.8) -> bool:
        return self.limit is not None and self.ratio >= warn_ratio

    def to_dict(self, warn_ratio: float = 0.8) -> dict:
        return {
            "limit": self.limit,
            "used": self.used,
            "planned": self.planned,
            "remaining": self.remaining,
            "remaining_after": self.remaining_after,
            "would_exceed": self.would_exceed,
            "warn": self.warn(warn_ratio),
            "percent": round(self.ratio * 100),
        }


def planned_messages(recipient_count: int, send_count: int = 1) -> int:
    """通数 = 配信回数 × 対象友だち数。"""
    return max(recipient_count, 0) * max(send_count, 0)
