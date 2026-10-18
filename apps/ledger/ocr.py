"""レシート・報酬明細の読み取り（Claude vision / PDF）。"""
from __future__ import annotations

import io
import logging
from datetime import date

from apps.ai import services as ai_services
from apps.ai.claude_client import AIError

from .categories import CATEGORY_BY_CODE
from .models import IncomeStatement, Receipt

logger = logging.getLogger(__name__)

MAX_SIDE = 2000


def prepare_document(file_field) -> tuple[bytes, str]:
    """画像は JPEG に正規化して縮小（HEIC 等の変換・トークン削減）。PDF はそのまま。"""
    with file_field.open("rb") as f:
        data = f.read()
    name = (file_field.name or "").lower()
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        return data, "application/pdf"
    try:
        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception as exc:  # noqa: BLE001
        raise AIError("画像を読み込めませんでした。JPEG/PNG/PDF でアップロードしてください。") from exc


def run_receipt_ocr(receipt_id: int) -> None:
    receipt = Receipt.objects.get(pk=receipt_id)
    receipt.status = Receipt.Status.PROCESSING
    receipt.save(update_fields=["status", "updated_at"])
    try:
        data, media_type = prepare_document(receipt.file)
        result = ai_services.ocr_receipt(data, media_type)
        if result.get("suggested_category") not in CATEGORY_BY_CODE:
            result["suggested_category"] = "misc"
        receipt.ocr_raw = result
        receipt.status = Receipt.Status.DONE
        receipt.error = ""
    except AIError as exc:
        receipt.status = Receipt.Status.FAILED
        receipt.error = str(exc)
    except Exception:  # noqa: BLE001
        logger.exception("receipt ocr failed %s", receipt_id)
        receipt.status = Receipt.Status.FAILED
        receipt.error = "読み取り中に予期しないエラーが発生しました"
    receipt.save(update_fields=["ocr_raw", "status", "error", "updated_at"])


def _int_or_none(value):
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def apply_statement_ocr(statement: IncomeStatement, result: dict) -> None:
    statement.ocr_raw = result
    if result.get("period_year") and result.get("period_month"):
        statement.year = int(result["period_year"])
        statement.month = max(1, min(12, int(result["period_month"])))
    statement.salon_name = (result.get("salon_name") or statement.salon_name)[:100]
    statement.gross_sales = _int_or_none(result.get("gross_sales"))
    statement.commission_rate_pct = result.get("commission_rate_pct")
    statement.commission_amount = _int_or_none(result.get("commission_amount")) or 0
    statement.deductions = [
        {"label": (d.get("label") or "控除")[:100], "amount": _int_or_none(d.get("amount")) or 0} for d in result.get("deductions", []) if isinstance(d, dict)
    ]
    statement.withholding_tax = _int_or_none(result.get("withholding_tax")) or 0
    statement.net_paid = _int_or_none(result.get("net_paid")) or 0
    if result.get("paid_on"):
        try:
            statement.paid_on = date.fromisoformat(str(result["paid_on"])[:10])
        except ValueError:
            pass
    if result.get("notes"):
        statement.notes = (statement.notes + "\n" if statement.notes else "") + f"[読み取りメモ] {result['notes']}"


def run_statement_ocr(statement_id: int) -> None:
    statement = IncomeStatement.objects.get(pk=statement_id)
    if not statement.document:
        statement.status = IncomeStatement.Status.DRAFT
        statement.save(update_fields=["status", "updated_at"])
        return
    try:
        data, media_type = prepare_document(statement.document)
        result = ai_services.ocr_statement(data, media_type)
        apply_statement_ocr(statement, result)
        statement.status = IncomeStatement.Status.DRAFT
        statement.error = ""
    except AIError as exc:
        statement.status = IncomeStatement.Status.FAILED
        statement.error = str(exc)
    except Exception:  # noqa: BLE001
        logger.exception("statement ocr failed %s", statement_id)
        statement.status = IncomeStatement.Status.FAILED
        statement.error = "読み取り中に予期しないエラーが発生しました"
    statement.save()
