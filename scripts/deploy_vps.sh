#!/usr/bin/env bash
# Переезд на VPS: образы, файлы, база, HTTPS, вебхук — за один запуск.
#
# Перед первым запуском:  py -3 scripts/vps_bootstrap.py IP ПАРОЛЬ
# Запуск:                 bash scripts/deploy_vps.sh IP [ДОМЕН]
#
# Без ДОМЕНА адрес будет вида 1-2-3-4.sslip.io: такой домен сам указывает на IP,
# покупать ничего не нужно, Caddy получает на него сертификат Let's Encrypt.
#
# Что делает: ставит Docker и подкачку, переносит образы (сервер их не собирает —
# на 1 ГБ памяти сборка фронтенда может не влезть), файлы проекта и дамп базы,
# поднимает db + app + caddy, ждёт HTTPS снаружи, переподписывает вебхук,
# останавливает локальную копию (иначе бот будет слать уведомления дважды),
# гоняет сквозной тест через публичный адрес и сбрасывает демо-данные.
set -euo pipefail
cd "$(dirname "$0")/.."

IP="${1:?Укажите IP сервера}"
HOST="${2:-${IP//./-}.sslip.io}"
URL="https://$HOST"
KEY="$HOME/.ssh/max_campus_vps"
REMOTE_DIR=/opt/max-campus     # имя каталога = имя проекта compose = префикс образа max-campus-app
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 "root@$IP")
PY="$(command -v python || echo 'py -3')"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1

env_get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r' || true; }
OLD_URL="$(env_get MINIAPP_PUBLIC_URL)"

echo "==> Сервер $IP, адрес $URL"
"${SSH[@]}" true || { echo "Нет доступа по ключу. Сначала: py -3 scripts/vps_bootstrap.py $IP ПАРОЛЬ"; exit 1; }

echo "==> Docker и подкачка на сервере"
"${SSH[@]}" bash -s <<'REMOTE'
set -e
export DEBIAN_FRONTEND=noninteractive
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh || { apt-get update -q && apt-get install -yq docker.io docker-compose-v2; }
fi
systemctl enable --now docker >/dev/null 2>&1 || true
if [ "$(swapon --show | wc -l)" -eq 0 ]; then
  fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
if command -v ufw >/dev/null && ufw status | grep -q active; then ufw allow 22/tcp; ufw allow 80/tcp; ufw allow 443/tcp; fi
docker --version; docker compose version
REMOTE

echo "==> Собираю образ локально и переношу образы"
docker compose build app
docker pull -q caddy:2-alpine >/dev/null
docker save max-campus-app:latest pgvector/pgvector:pg16 caddy:2-alpine | gzip -1 | "${SSH[@]}" "gunzip | docker load"

echo "==> Переношу файлы проекта"
tar -czf - --exclude=.git --exclude=node_modules --exclude=tmp --exclude=__pycache__ \
    --exclude=frontend/dist --exclude=.env \
    docker-compose.yml scripts certs backend frontend DATA-API.yaml README.md \
  | "${SSH[@]}" "mkdir -p $REMOTE_DIR && tar -xzf - -C $REMOTE_DIR"
# .env — отдельно, с адресом сервера и сторожем вебхука. Туннели на сервере не нужны.
sed -e "s|^MINIAPP_PUBLIC_URL=.*|MINIAPP_PUBLIC_URL=$URL|" -e "/^PUBLIC_HOST=/d" .env \
  | sed "/^BOT_WEBHOOK_AUTOSUBSCRIBE=/d" | { cat; echo "PUBLIC_HOST=$HOST"; echo "BOT_WEBHOOK_AUTOSUBSCRIBE=true"; } | "${SSH[@]}" "cat > $REMOTE_DIR/.env && chmod 600 $REMOTE_DIR/.env"

echo "==> Переношу базу"
docker compose up -d db >/dev/null
docker exec campus-db pg_dump -U campus -d campus -Fc > tmp/deploy.dump
"${SSH[@]}" "cd $REMOTE_DIR && docker compose up -d db && for i in \$(seq 1 30); do docker exec campus-db pg_isready -U campus -d campus >/dev/null 2>&1 && break; sleep 2; done"
"${SSH[@]}" "docker exec -i campus-db pg_restore -U campus -d campus --clean --if-exists --no-owner" < tmp/deploy.dump \
  || echo "   (pg_restore выдал предупреждения — обычно это DROP несуществующих объектов)"

echo "==> Запускаю приложение и HTTPS"
"${SSH[@]}" "cd $REMOTE_DIR && docker compose --profile vps up -d --no-build"

echo "==> Жду, пока $URL ответит"
ok=""
for _ in $(seq 1 40); do
  curl -fsS -m 10 "$URL/api/health" >/dev/null 2>&1 && { ok=1; break; }
  sleep 5
done
if [[ -z "$ok" ]]; then
  echo "Адрес не отвечает. Логи:"
  "${SSH[@]}" "cd $REMOTE_DIR && docker compose --profile vps logs --tail=30 caddy app"
  exit 1
fi
echo "    $URL/api/health → OK"

echo "==> Останавливаю локальную копию и туннели"
docker compose --profile tunnel --profile ngrok --profile tuna stop >/dev/null 2>&1 || true

echo "==> Переподписываю вебхук бота"
if [[ -n "$OLD_URL" && "$OLD_URL" != "$URL" && "$OLD_URL" == https://* ]]; then
  $PY scripts/setup_bot.py unsubscribe "$OLD_URL/webhook/max" || true
fi
$PY scripts/setup_bot.py subscribe "$URL/webhook/max"
sed -i "s|^MINIAPP_PUBLIC_URL=.*|MINIAPP_PUBLIC_URL=$URL|" .env

echo "==> Сквозной тест через публичный адрес"
$PY scripts/smoke_test.py "$URL" | tail -4

echo "==> Сбрасываю демо-данные (тест занимает коды привязки)"
"${SSH[@]}" "cd $REMOTE_DIR && bash scripts/reset_demo.sh" | tail -3

sed -i -E "s#https://(REPLACE-WITH-CURRENT-TUNNEL|[a-z0-9-]+\.(trycloudflare\.com|ngrok-free\.app|ngrok-free\.dev)|[a-z0-9.-]+\.tuna\.am|[0-9-]+\.sslip\.io)#$URL#g" DATA-API.yaml

echo
echo "Готово. Ссылка для сдачи: $URL"
