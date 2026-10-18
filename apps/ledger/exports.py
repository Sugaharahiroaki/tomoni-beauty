"""CSV 出力（汎用仕訳帳 / 弥生会計 仕訳日記帳 / freee 取引 / e-Tax 転記表 / 経費・収入一覧）。

各会計ソフトの取込仕様は変更されることがあるため、取り込み前にソフト側の最新仕様と列順を確認する前提（docs/LEDGER.md）。
"""
from __future__ import annotations

import csv
import io
from datetime import date

from .categories import category_label
from .journal import Entry


def _csv(rows: list[list], header: list[str] | None = None) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    if header:
        writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def _d(d: date) -> str:
    return d.strftime("%Y/%m/%d")


def journal_csv_generic(entries: list[Entry]) -> str:
    rows = [[_d(e.date), e.debit, e.amount, e.credit, e.amount, e.description, e.source] for e in entries]
    return _csv(rows, ["日付", "借方科目", "借方金額", "貸方科目", "貸方金額", "摘要", "区分"])


def journal_csv_yayoi(entries: list[Entry]) -> str:
    """弥生会計「仕訳日記帳」インポート形式（25列・ヘッダー無し）。

    識別フラグ 2000 = 1行仕訳。税区分は免税事業者前提で「対象外」。
    """
    rows = []
    for i, e in enumerate(entries, start=1):
        rows.append(
            [
                "2000",  # 識別フラグ
                str(i),  # 伝票No
                "",  # 決算
                _d(e.date),  # 取引日付
                e.debit,  # 借方勘定科目
                "",  # 借方補助科目
                "",  # 借方部門
                "対象外",  # 借方税区分
                e.amount,  # 借方金額
                0,  # 借方税金額
                e.credit,  # 貸方勘定科目
                "",  # 貸方補助科目
                "",  # 貸方部門
                "対象外",  # 貸方税区分
                e.amount,  # 貸方金額
                0,  # 貸方税金額
                e.description,  # 摘要
                "",  # 番号
                "",  # 期日
                "0",  # タイプ
                "",  # 生成元
                "",  # 仕訳メモ
                "0",  # 付箋1
                "0",  # 付箋2
                "no",  # 調整
            ]
        )
    return _csv(rows)


def freee_csv(expenses, statements, other_incomes) -> str:
    """freee 会計「取引」インポート形式。収入は報酬（控除前）、支出は経費（事業分）。"""
    header = ["収支区分", "管理番号", "発生日", "決済期日", "取引先", "勘定科目", "税区分", "金額", "税計算区分", "税額", "備考", "品目", "部門", "メモタグ（複数指定可、カンマ区切り）", "セグメント1", "セグメント2", "セグメント3", "決済日", "決済口座", "決済金額"]
    rows = []
    for s in statements:
        rows.append(["収入", f"S{s.pk}", _d(s.period_end), _d(s.paid_on) if s.paid_on else "", s.salon_name, "売上高", "対象外", s.commission_amount, "", "", f"{s.month}月分 報酬", "", "", "TOMONI", "", "", "", _d(s.paid_on) if s.paid_on else "", "普通預金" if s.paid_on else "", s.net_paid if s.paid_on else ""])
    for e in expenses:
        account = {"cash": "現金", "bank": "普通預金", "private": "事業主借", "statement": "売掛金"}.get(e.payment_method, "事業主借")
        rows.append(["支出", f"E{e.pk}", _d(e.date), "", e.vendor, e.account_name, "対象外", e.business_amount, "", "", f"{category_label(e.category)} {e.description}".strip(), "", "", "TOMONI", "", "", "", _d(e.date), account, e.business_amount])
    for o in other_incomes:
        rows.append(["収入", f"O{o.pk}", _d(o.date), "", "", "雑収入", "対象外", o.amount, "", "", o.description, "", "", "TOMONI", "", "", "", _d(o.date), "現金" if o.received_to == "cash" else "普通預金", o.amount])
    return _csv(rows, header)


def etax_summary_csv(decision: dict, estimate: dict | None) -> str:
    rows = [["青色申告決算書（損益計算書）", "", ""]]
    for label, amount in decision["lines"]:
        rows.append(["", label, amount])
    rows.append(["", "", ""])
    rows.append(["貸借対照表", "", ""])
    bs = decision["bs"]
    for name, amount in bs["assets"].items():
        rows.append(["資産", name, amount])
    rows.append(["資産", "事業主貸", bs["drawings"]])
    rows.append(["資産", "合計", bs["total_assets"]])
    rows.append(["負債・資本", "事業主借", bs["owner_credit"]])
    rows.append(["負債・資本", "元入金", bs["capital"]])
    rows.append(["負債・資本", "青色申告特別控除前の所得金額", bs["net_income"]])
    rows.append(["負債・資本", "合計", bs["total_liabilities_equity"]])
    if estimate:
        rows.append(["", "", ""])
        rows.append(["確定申告書（転記の目安・概算）", "", ""])
        rows.append(["", "事業所得", estimate["business_income"]])
        rows.append(["", "社会保険料控除（概算）", estimate["social_insurance"]])
        rows.append(["", "基礎控除", estimate["basic_deduction"]])
        rows.append(["", "その他の所得控除", estimate["other_deductions"]])
        rows.append(["", "課税される所得金額", estimate["taxable_income"]])
        rows.append(["", "所得税額（復興特別所得税含む・概算）", estimate["income_tax"]])
        rows.append(["", "源泉徴収税額", estimate["withheld"]])
        rows.append(["", "納付（＋）／還付（−）見込み", estimate["balance_due"]])
    return _csv(rows, ["区分", "項目", "金額"])


def expenses_csv(expenses) -> str:
    rows = [[_d(e.date), category_label(e.category), e.account_name, e.vendor, e.description, e.amount, e.business_ratio, e.business_amount, e.get_payment_method_display(), e.get_status_display()] for e in expenses]
    return _csv(rows, ["日付", "科目", "勘定科目", "支払先", "内容", "金額", "事業割合%", "事業分金額", "支払方法", "状態"])


def income_csv(statements) -> str:
    rows = [[s.year, s.month, s.salon_name, s.gross_sales or "", s.commission_rate_pct or "", s.commission_amount, s.deductions_total, s.withholding_tax, s.net_paid, _d(s.paid_on) if s.paid_on else ""] for s in statements]
    return _csv(rows, ["年", "月", "サロン", "技術売上", "歩合率%", "報酬額", "控除合計", "源泉徴収", "差引支給額", "支払日"])


def encode(text: str, encoding: str) -> bytes:
    if encoding.lower() in ("cp932", "shift_jis"):
        return text.encode("cp932", errors="replace")
    return ("﻿" + text).encode("utf-8")
