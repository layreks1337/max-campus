#!/usr/bin/env bash
# Публикация по постоянному адресу — для сдачи и на весь период проверки.
#
# Туннель выбирается в .env строкой PUBLIC_TUNNEL=tuna|ngrok (по умолчанию tuna).
#   tuna:  TUNA_TOKEN, TUNA_SUBDOMAIN   (токен — my.tuna.am, нужен платный тариф)
#   ngrok: NGROK_AUTHTOKEN, NGROK_DOMAIN (с российских IP не работает: ERR_NGROK_9040)
#
# Что делает: поднимает выбранный туннель и гасит остальные, узнаёт публичный
# адрес, прописывает его в MINIAPP_PUBLIC_URL, перезапускает приложение, ждёт,
# пока адрес ответит снаружи, переподписывает вебхук бота и обновляет DATA-API.yaml.
#
# Запуск:  bash scripts/go_public.sh
set -euo pipefail
cd "$(dirname "$0")/.."

env_get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r' || true; }
env_set() {
  if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
}

TUNNEL="$(env_get PUBLIC_TUNNEL)"; TUNNEL="${TUNNEL:-tuna}"
OLD_URL="$(env_get MINIAPP_PUBLIC_URL)"
PY="$(command -v python || echo 'py -3')"
ALL_TUNNELS="tunnel ngrok tuna"   # сервисы в docker-compose; tunnel — quick-туннель cloudflared

case "$TUNNEL" in
  tuna)
    TOKEN="$(env_get TUNA_TOKEN)"; SUB="$(env_get TUNA_SUBDOMAIN)"
    if [[ -z "$TOKEN" || -z "$SUB" ]]; then
      echo "В .env не заданы TUNA_TOKEN и/или TUNA_SUBDOMAIN."
      echo "  токен: https://my.tuna.am (нужен тариф с резервированием поддоменов)"
      exit 1
    fi
    SERVICE=tuna ;;
  ngrok)
    TOKEN="$(env_get NGROK_AUTHTOKEN)"; DOMAIN="$(env_get NGROK_DOMAIN)"
    # Адрес часто копируют целиком — оставляем только хост.
    DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN%%/*}"
    if [[ -z "$TOKEN" || -z "$DOMAIN" ]]; then
      echo "В .env не заданы NGROK_AUTHTOKEN и/или NGROK_DOMAIN."
      exit 1
    fi
    env_set NGROK_DOMAIN "$DOMAIN"
    SERVICE=ngrok ;;
  *)
    echo "PUBLIC_TUNNEL=$TUNNEL — поддерживаются tuna и ngrok"; exit 1 ;;
esac

echo "==> Туннель: $TUNNEL. Гашу остальные"
for s in $ALL_TUNNELS; do
  [[ "$s" == "$SERVICE" ]] || docker compose --profile "$s" rm -sf "$s" >/dev/null 2>&1 || true
done

echo "==> Поднимаю базу и приложение"
docker compose up -d --build db app

echo "==> Запускаю $SERVICE"
docker compose --profile "$SERVICE" up -d --force-recreate "$SERVICE"

echo "==> Узнаю публичный адрес"
URL=""
if [[ "$SERVICE" == ngrok ]]; then
  URL="https://$DOMAIN"
else
  for _ in $(seq 1 30); do
    URL="$(docker compose logs "$SERVICE" 2>/dev/null | grep -oE "https://[a-z0-9.-]+\.tuna\.am" | tail -1 || true)"
    [[ -n "$URL" ]] && break
    sleep 2
  done
  if [[ -z "$URL" ]]; then
    echo "tuna не выдал адрес. Логи:"
    docker compose logs --tail=30 "$SERVICE"
    exit 1
  fi
fi
echo "    $URL"

echo "==> Прописываю адрес и перезапускаю приложение"
env_set MINIAPP_PUBLIC_URL "$URL"
docker compose up -d --force-recreate app
for _ in $(seq 1 60); do
  curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
  sleep 3
done
curl -fsS http://127.0.0.1:8000/api/health >/dev/null || { echo "Приложение не поднялось"; docker compose logs --tail=40 app; exit 1; }

echo "==> Жду, пока адрес ответит снаружи"
ok=""
for _ in $(seq 1 30); do
  if curl -fsS -H "ngrok-skip-browser-warning: 1" "$URL/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 3
done
if [[ -z "$ok" ]]; then
  echo "Адрес $URL не отвечает. Логи $SERVICE:"
  docker compose logs --tail=30 "$SERVICE"
  exit 1
fi
echo "    $URL/api/health → OK"

echo "==> Переподписываю вебхук бота"
if [[ -n "$OLD_URL" && "$OLD_URL" != "$URL" && "$OLD_URL" == https://* ]]; then
  $PY scripts/setup_bot.py unsubscribe "$OLD_URL/webhook/max" || true
fi
$PY scripts/setup_bot.py subscribe "$URL/webhook/max"

echo "==> Обновляю адрес в DATA-API.yaml"
sed -i -E "s#https://(REPLACE-WITH-CURRENT-TUNNEL|[a-z0-9-]+\.(trycloudflare\.com|ngrok-free\.app|ngrok-free\.dev|ngrok\.app|ngrok\.dev)|[a-z0-9.-]+\.tuna\.am)#$URL#g" DATA-API.yaml

echo
echo "Готово. Ссылка для сдачи: $URL"
