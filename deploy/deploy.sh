#!/usr/bin/env bash
# GitHub Actions から SSH で呼ばれるデプロイスクリプト（tomoni ユーザーで実行）
set -euo pipefail
APP_DIR=/srv/tomoni-beauty
cd "$APP_DIR"

git fetch --all --prune
git reset --hard origin/main

.venv/bin/pip install -q -r requirements.txt

set -a; . ./.env; set +a
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check --deploy --fail-level ERROR

sudo systemctl restart tomoni-web tomoni-worker
sleep 2
curl -fsS http://127.0.0.1:8000/health/ >/dev/null && echo "deploy ok: $(git rev-parse --short HEAD)"
