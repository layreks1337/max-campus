#!/usr/bin/env bash
# Выкладка на VPS: образы, файлы, база (только в первый раз), HTTPS, вебхук.
#
# Перед первым запуском:  py -3 scripts/vps_bootstrap.py IP ПАРОЛЬ
# Запуск:                 bash scripts/deploy_vps.sh IP [ДОМЕН]
#   REF=<коммит|тег>      что выкладывать (по умолчанию HEAD). На сервер уходит
#                         только закоммиченное — незавершённые правки не попадут.
#   SKIP_SMOKE=1          не гонять сквозной тест (он создаёт заявки и занимает коды).
#
# Без ДОМЕНА адрес будет вида 1-2-3-4.sslip.io: такой домен сам указывает на IP,
# покупать ничего не нужно, Caddy получает на него сертификат Let's Encrypt.
#
# Сервер образы не собирает — на 1 ГБ памяти сборка фронтенда может не влезть.
# База переносится, только если на сервере она пустая: при повторной выкладке
# данные проверяющих не затираются. Предыдущий образ остаётся как max-campus-app:prev.
set -euo pipefail
cd "$(dirname "$0")/.."

IP="${1:?Укажите IP сервера}"
HOST="${2:-${IP//./-}.sslip.io}"
URL="https://$HOST"
REF="${REF:-HEAD}"
KEY="$HOME/.ssh/max_campus_vps"
REMOTE_DIR=/opt/max-campus     # имя каталога = имя проекта compose = префикс образа max-campus-app
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 "root@$IP")
PY="$(command -v python || echo 'py -3')"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1

env_get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r' || true; }
OLD_URL="$(env_get MINIAPP_PUBLIC_URL)"
COMMIT="$(git rev-parse --short "$REF")"

echo "==> Сервер $IP, адрес $URL, версия $COMMIT"
"${SSH[@]}" true || { echo "Нет доступа по ключу. Сначала: py -3 scripts/vps_bootstrap.py $IP ПАРОЛЬ"; exit 1; }

echo "==> Docker, подкачка и файрвол на сервере"
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
# Наружу — только SSH и веб. Порты базы и приложения и так привязаны к 127.0.0.1.
command -v ufw >/dev/null || apt-get install -yq ufw >/dev/null
ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
docker --version; docker compose version
REMOTE

echo "==> Экспортирую $COMMIT и собираю образ"
EXPORT_DIR="$(mktemp -d)"
trap 'rm -rf "$EXPORT_DIR"' EXIT
git archive "$REF" | tar -x -C "$EXPORT_DIR"
docker build -q -f "$EXPORT_DIR/backend/Dockerfile" -t max-campus-app:deploy "$EXPORT_DIR"
docker pull -q caddy:2-alpine >/dev/null
docker pull -q pgvector/pgvector:pg16 >/dev/null

echo "==> Переношу образы (прошлый остаётся как :prev)"
"${SSH[@]}" "docker tag max-campus-app:latest max-campus-app:prev 2>/dev/null || true"
docker save max-campus-app:deploy pgvector/pgvector:pg16 caddy:2-alpine | gzip -1 \
  | "${SSH[@]}" "gunzip | docker load && docker tag max-campus-app:deploy max-campus-app:latest"

echo "==> Переношу файлы проекта"
tar -czf - -C "$EXPORT_DIR" . | "${SSH[@]}" "mkdir -p $REMOTE_DIR && tar -xzf - -C $REMOTE_DIR"
# .env — отдельно, с адресом сервера и сторожем вебхука. Туннели на сервере не нужны.
sed -e "s|^MINIAPP_PUBLIC_URL=.*|MINIAPP_PUBLIC_URL=$URL|" -e "/^PUBLIC_HOST=/d" .env \
  | sed "/^BOT_WEBHOOK_AUTOSUBSCRIBE=/d" | { cat; echo "PUBLIC_HOST=$HOST"; echo "BOT_WEBHOOK_AUTOSUBSCRIBE=true"; } | "${SSH[@]}" "cat > $REMOTE_DIR/.env && chmod 600 $REMOTE_DIR/.env"
echo "$COMMIT" | "${SSH[@]}" "cat > $REMOTE_DIR/DEPLOYED_COMMIT"

echo "==> База"
"${SSH[@]}" "cd $REMOTE_DIR && docker compose up -d db && for i in \$(seq 1 30); do docker exec campus-db pg_isready -U campus -d campus >/dev/null 2>&1 && break; sleep 2; done"
TABLES="$("${SSH[@]}" "docker exec campus-db psql -U campus -d campus -tAc \"select count(*) from information_schema.tables where table_schema='public'\"" | tr -d '[:space:]')"
if [[ "$TABLES" == "0" ]]; then
  echo "    на сервере пусто — переношу локальную"
  mkdir -p tmp
  docker compose up -d db >/dev/null
  docker exec campus-db pg_dump -U campus -d campus -Fc > tmp/deploy.dump
  "${SSH[@]}" "docker exec -i campus-db pg_restore -U campus -d campus --no-owner" < tmp/deploy.dump \
    || echo "    (pg_restore выдал предупреждения — проверю по здоровью приложения)"
else
  echo "    на сервере уже $TABLES таблиц — данные не трогаю"
fi

echo "==> Запускаю приложение и HTTPS"
"${SSH[@]}" "cd $REMOTE_DIR && docker compose --profile vps up -d --no-build && docker compose --profile vps up -d --no-build --force-recreate app"

echo "==> Жду, пока $URL ответит"
ok=""
for _ in $(seq 1 40); do
  curl -fsS -m 10 "$URL/api/health" >/dev/null 2>&1 && { ok=1; break; }
  sleep 5
done
if [[ -z "$ok" ]]; then
  echo "Адрес не отвечает. Логи (откат: docker tag max-campus-app:prev max-campus-app:latest):"
  "${SSH[@]}" "cd $REMOTE_DIR && docker compose --profile vps logs --tail=30 caddy app"
  exit 1
fi
echo "    $URL/api/health → OK"

echo "==> Гашу локальные туннели (локальное приложение остаётся для разработки)"
docker compose --profile tunnel --profile ngrok --profile tuna stop tunnel ngrok tuna >/dev/null 2>&1 || true

echo "==> Переподписываю вебхук бота"
if [[ -n "$OLD_URL" && "$OLD_URL" != "$URL" && "$OLD_URL" == https://* ]]; then
  $PY scripts/setup_bot.py unsubscribe "$OLD_URL/webhook/max" || true
fi
$PY scripts/setup_bot.py subscribe "$URL/webhook/max"
sed -i "s|^MINIAPP_PUBLIC_URL=.*|MINIAPP_PUBLIC_URL=$URL|" .env

if [[ -z "${SKIP_SMOKE:-}" ]]; then
  echo "==> Сквозной тест через публичный адрес"
  $PY scripts/smoke_test.py "$URL" | tail -4
fi

echo "==> Сбрасываю демо-данные (тест занимает коды привязки)"
"${SSH[@]}" "cd $REMOTE_DIR && bash scripts/reset_demo.sh" | tail -3

echo
echo "Готово. Версия $COMMIT на $URL"
