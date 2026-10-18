# n8n ワークフロー

## daily_digest_workflow.json

毎朝8時（JST）に次を行います。

1. `POST {SITE_URL}/internal/cron/daily/` — 期日になったフォロー案内の下書き生成、LINE通数の取得
2. `GET {SITE_URL}/internal/digest/` — 美容師ごとの「今日のおすすめ対応」件数を取得
3. 対応がある美容師にだけメールで通知（通数を消費しない通知手段としてメールを採用）

### 設定

n8n の環境変数（または Variables）に以下を設定してください。

| 変数 | 内容 |
| --- | --- |
| `TOMONI_SITE_URL` | 例 `https://app.example.com` |
| `TOMONI_INTERNAL_TOKEN` | アプリの `.env` の `INTERNAL_API_TOKEN` と同じ値 |
| `TOMONI_MAIL_FROM` | 通知メールの From |

「メールで通知」ノードの SMTP クレデンシャルを自分のものに差し替えてください。

### n8n を使わない場合

同じ処理は cron でも実行できます。

```
0 8 * * * cd /srv/tomoni-beauty && set -a && . ./.env && set +a && .venv/bin/python manage.py run_daily >> /var/log/tomoni-daily.log 2>&1
```

## 第2段階で追加予定

- SALON BOARD 予約通知メールの IMAP 受信 → 解析 → `POST /internal/reservations/`（未実装。`docs/HOTPEPPER.md` 参照）
