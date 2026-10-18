# デプロイ手順（さくらVPS + GitHub Actions）

## 構成

```
GitHub (main) ──push──▶ GitHub Actions (pytest → SSH) ──▶ VPS: deploy/deploy.sh
                                                             ├─ nginx (80/443) → gunicorn (127.0.0.1:8000)
                                                             ├─ systemd: tomoni-web (gunicorn), tomoni-worker (qcluster)
                                                             ├─ PostgreSQL
                                                             └─ n8n（任意・同VPS or 別）→ /internal/cron/daily/
```

## 1. 初回セットアップ（VPS、root）

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/tomoni-beauty/main/deploy/setup_server.sh -o setup_server.sh
bash setup_server.sh git@github.com:<owner>/tomoni-beauty.git app.example.com
```

スクリプトが行うこと: apt パッケージ、`tomoni` ユーザー、PostgreSQL の DB/ユーザー作成、`/srv/tomoni-beauty` に clone、venv、`.env` 生成（シークレット自動生成）、migrate / collectstatic、systemd ユニット登録、nginx 設定。

その後:

```bash
# APIキーを記入
sudo -u tomoni nano /srv/tomoni-beauty/.env    # ANTHROPIC_API_KEY, OPENAI_API_KEY
sudo systemctl restart tomoni-web tomoni-worker
# TLS
certbot --nginx -d app.example.com
# 管理ユーザー
sudo -u tomoni bash -c 'cd /srv/tomoni-beauty && set -a && . ./.env && set +a && .venv/bin/python manage.py createsuperuser'
```

デプロイ用の SSH 鍵: `tomoni` ユーザーに鍵を登録し、`deploy.sh` 内の `sudo systemctl restart` を許可するため `/etc/sudoers.d/tomoni` に

```
tomoni ALL=(root) NOPASSWD: /bin/systemctl restart tomoni-web tomoni-worker
```

## 2. GitHub Actions

- `.github/workflows/ci.yml`: すべてのブランチで `makemigrations --check` と `pytest`。
- `.github/workflows/deploy.yml`: `main` への push でテスト → SSH で `deploy/deploy.sh`。

Repository → Settings → Environments → `production` に Secrets を登録:

| Secret | 内容 |
| --- | --- |
| `SSH_HOST` | VPS のホスト名 / IP |
| `SSH_USER` | `tomoni` |
| `SSH_PRIVATE_KEY` | デプロイ用秘密鍵 |
| `SSH_PORT` | 省略可（22） |

## 3. 環境変数（`.env`）

`.env.example` を参照。本番で必ず変えるもの: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL`, `DATABASE_URL`, `Q_SYNC=false`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `INTERNAL_API_TOKEN`。

## 3.1 リッチメニュー画像の日本語フォント

自動生成するリッチメニュー画像には日本語フォントが必要です。`setup_server.sh` は `fonts-noto-cjk` を入れます。別のフォントを使う場合は `.env` に `RICH_MENU_FONT_PATH=/path/to/font.ttc` を指定してください。

## 3.2 SNS動画（リール）に必要なもの

- `apt install ffmpeg fonts-noto-cjk`（`setup_server.sh` に含む）
- `.env`: `GEMINI_API_KEY`（ナレーション）、`FIELD_ENCRYPTION_KEY`（接続トークンの暗号化鍵。`python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` で生成）、`PUBLIC_MEDIA_BASE_URL=https://<ドメイン>/media`、`RENDER_WORK_DIR=/var/lib/tomoni/render_work`
- 定期処理の登録（予約投稿・数値取り込み・日次処理）: `python manage.py setup_schedules`（qcluster が実行）
- Nginx は `/media/` を Django に通し、`/protected-media/`（internal）で送り出す（`deploy/nginx/tomoni.conf`）
- 外部サービスの申請手順は `docs/REELS.md` §6

## 4. 日次処理

n8n（`n8n/README.md`）か cron:

```
0 8 * * * cd /srv/tomoni-beauty && set -a && . ./.env && set +a && .venv/bin/python manage.py run_daily >> /var/log/tomoni-daily.log 2>&1
```

## 5. バックアップ

```bash
# DB（毎日）
sudo -u postgres pg_dump tomoni | gzip > /var/backups/tomoni-$(date +%F).sql.gz
# メディア（施術写真）
rsync -a /srv/tomoni-beauty/media/ /var/backups/tomoni-media/
```

## 6. 運用メモ

- ログ: `journalctl -u tomoni-web -f` / `journalctl -u tomoni-worker -f`
- ジョブの状況: 管理画面 `/admin/django_q/`（失敗タスクの再実行も可能）
- LINE Webhook が届かない: 設定 › LINE連携 の Webhook URL と LINE Developers の設定を照合、`journalctl -u tomoni-web | grep signature`
- ヘルスチェック: `GET /health/` → `{"status":"ok"}`
- 開発環境: `python -m venv .venv && pip install -r requirements-dev.txt && cp .env.example .env && python manage.py migrate && python manage.py runserver`（APIキー無しでもダミーAIで動作）

## 自動デプロイを有効にするまで（いまは GitHub をバックアップとして使う段階）

`deploy.yml` の deploy ジョブは、リポジトリ変数 `DEPLOY_ENABLED` が `true` のとき（または Actions 画面からの手動実行）だけ動きます。サーバーの準備ができる前に main へ push しても「missing server host」で失敗しないようにするためです。

1. GitHub の Settings → Secrets and variables → Actions → **Secrets** に `SSH_HOST` `SSH_USER` `SSH_PRIVATE_KEY`（必要なら `SSH_PORT`）を登録
2. 同じ画面の **Variables** に `DEPLOY_ENABLED` = `true` を登録
3. 以後、main への push でテスト → デプロイが自動で走る（テストの `test` ジョブはこの変数に関係なく毎回走る）
