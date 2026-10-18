# n8n ワークフロー

## daily_digest_workflow.json — 日次処理と「今日のおすすめ対応」メール

毎朝8時（JST）に次を行います。

1. `POST {SITE_URL}/internal/cron/daily/` — 期日になったフォロー案内の下書き生成、LINE通数の取得
2. `GET {SITE_URL}/internal/digest/` — 美容師ごとの「今日のおすすめ対応」件数を取得
3. 対応がある美容師にだけメールで通知（通数を消費しない通知手段としてメールを採用）

## reservation_email_workflow.json — SALON BOARD 予約通知メールの取り込み

1. 取り込み用メールボックス（例: Gmail のエイリアス）を IMAP で監視（未読のみ）
2. 件名に「予約」を含むメールを `POST {SITE_URL}/internal/reservations/email/` に送る
3. アプリ側で日時・氏名・メニューを解析（正規表現 → 足りなければ Claude）→ 顧客と照合 → 予約に登録。照合できなければ「要確認」として一覧に表示

店側の SALON BOARD「設定 › 基本設定 › 予約お知らせメール」に、この取り込み用アドレスを追加（または既存通知を転送）してもらう必要があります。
美容師ごとに `TOMONI_STYLIST_KEY`（アプリの「予約通知メールの取り込み」画面に表示）が異なるため、美容師ごとにワークフローを複製するか、メールボックスを分けてください。

### 設定（n8n の環境変数 / Variables）

| 変数 | 内容 |
| --- | --- |
| `TOMONI_SITE_URL` | 例 `https://app.example.com` |
| `TOMONI_INTERNAL_TOKEN` | アプリの `.env` の `INTERNAL_API_TOKEN` と同じ値 |
| `TOMONI_MAIL_FROM` | 通知メールの From（日次処理用） |
| `TOMONI_STYLIST_KEY` | 美容師の取り込みキー（予約メール取り込み用） |

クレデンシャル（SMTP / IMAP）はノード上で自分のものに差し替えてください。

## n8n を使わない場合

日次処理は cron でも実行できます。

```
0 8 * * * cd /srv/tomoni-beauty && set -a && . ./.env && set +a && .venv/bin/python manage.py run_daily >> /var/log/tomoni-daily.log 2>&1
```

予約メールは、アプリの「予約通知メールの取り込み」画面に本文を貼り付けても登録できます。
