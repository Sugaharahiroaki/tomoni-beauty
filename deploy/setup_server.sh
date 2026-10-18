#!/usr/bin/env bash
# さくらVPS（Ubuntu 24.04）初回セットアップ。root で実行。
# 使い方: bash setup_server.sh <GIT_REPO_URL> <DOMAIN>
set -euo pipefail

REPO_URL="${1:?git repo url}"
DOMAIN="${2:?domain}"
APP_DIR=/srv/tomoni-beauty
DB_PASS="$(openssl rand -hex 16)"

apt-get update
apt-get install -y python3 python3-venv python3-pip git nginx postgresql postgresql-contrib certbot python3-certbot-nginx libpq-dev build-essential fonts-noto-cjk

id -u tomoni &>/dev/null || useradd --system --create-home --shell /bin/bash tomoni

sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='tomoni'" | grep -q 1 || sudo -u postgres psql -c "CREATE USER tomoni WITH PASSWORD '${DB_PASS}';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='tomoni'" | grep -q 1 || sudo -u postgres psql -c "CREATE DATABASE tomoni OWNER tomoni;"

if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi
chown -R tomoni:tomoni "$APP_DIR"

sudo -u tomoni bash -c "cd $APP_DIR && python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  cat > "$APP_DIR/.env" <<EOF
DJANGO_SECRET_KEY=$(openssl rand -hex 32)
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=${DOMAIN}
DJANGO_CSRF_TRUSTED_ORIGINS=https://${DOMAIN}
SITE_URL=https://${DOMAIN}
DATABASE_URL=postgres://tomoni:${DB_PASS}@127.0.0.1:5432/tomoni
MEDIA_ROOT=${APP_DIR}/media
Q_SYNC=false
Q_WORKERS=2
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
CLAUDE_MODEL=claude-opus-5-5
TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
INTERNAL_API_TOKEN=$(openssl rand -hex 24)
SIGNUP_ENABLED=true
LOG_LEVEL=INFO
EOF
  chown tomoni:tomoni "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo ">>> $APP_DIR/.env を作成しました。ANTHROPIC_API_KEY / OPENAI_API_KEY を記入してください。"
fi

sudo -u tomoni bash -c "cd $APP_DIR && set -a && . ./.env && set +a && .venv/bin/python manage.py migrate --noinput && .venv/bin/python manage.py collectstatic --noinput"

cp "$APP_DIR/deploy/systemd/tomoni-web.service" /etc/systemd/system/
cp "$APP_DIR/deploy/systemd/tomoni-worker.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tomoni-web tomoni-worker

sed "s/app.example.com/${DOMAIN}/" "$APP_DIR/deploy/nginx/tomoni.conf" > /etc/nginx/sites-available/tomoni
ln -sf /etc/nginx/sites-available/tomoni /etc/nginx/sites-enabled/tomoni
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ">>> TLS: certbot --nginx -d ${DOMAIN} を実行してください"
echo ">>> 管理ユーザー: sudo -u tomoni bash -c 'cd $APP_DIR && set -a && . ./.env && set +a && .venv/bin/python manage.py createsuperuser'"
