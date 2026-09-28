#!/usr/bin/env bash
# Обслуживание VPS на период проверки: ночная копия базы и подъём после перезагрузки.
#
# Запускать НА СЕРВЕРЕ под root, из /opt/max-campus (туда его кладёт deploy_vps.sh):
#   bash scripts/vps_maintenance.sh          поставить задания cron и снять первую копию.
#                                            Повторный запуск ничего не дублирует —
#                                            файл /etc/cron.d/max-campus пишется целиком.
#   bash scripts/vps_maintenance.sh backup   снять копию сейчас (так его зовёт cron ночью)
#   bash scripts/vps_maintenance.sh up       поднять контейнеры (так его зовёт cron после перезагрузки)
#
# Копии лежат в /opt/max-campus/backups, хранятся 7 последних:
#   campus-ГГГГММДД-ЧЧММ.dump  база, pg_dump в формате custom
#   data-ГГГГММДД-ЧЧММ.tgz     том /data: выданные справки PDF и загрузки
# Восстановление:
#   docker exec -i campus-db pg_restore -U campus -d campus --clean --if-exists --no-owner < backups/campus-….dump
#   docker exec -i campus-app tar -xzf - -C /data < backups/data-….tgz
#
# Копии лежат на том же диске: они спасают от ошибки (лишний reset_demo.sh,
# неудачная выкладка), но не от потери сервера. Забрать к себе:
#   scp -i ~/.ssh/max_campus_vps root@IP:/opt/max-campus/backups/campus-*.dump .
set -euo pipefail
cd "$(dirname "$0")/.."

DIR="$(pwd)"
BACKUPS="$DIR/backups"
KEEP=7
CRON_FILE=/etc/cron.d/max-campus
LOG=/var/log/max-campus-maintenance.log
# Время сервера. На VPS это обычно UTC: 00:17 UTC — 03:17 МСК, 08:17 в Иркутске.
# pg_dump базы в десяток мегабайт идёт секунды и приложение не блокирует.
BACKUP_AT="17 0 * * *"

say() { echo "$(date '+%F %T') $*"; }

# Оставляет KEEP самых новых файлов по шаблону. Имена содержат дату — сортировка по имени.
rotate() {
  local old
  old="$(ls -1 "$BACKUPS"/$1 2>/dev/null | sort -r | tail -n +$((KEEP + 1)))" || true
  if [[ -n "$old" ]]; then
    echo "$old" | xargs rm -f --
  fi
}

backup() {
  mkdir -p "$BACKUPS"
  chmod 700 "$BACKUPS"   # в копиях персональные данные (пусть и синтетические)
  local stamp dump data
  stamp="$(date +%Y%m%d-%H%M)"
  dump="$BACKUPS/campus-$stamp.dump"
  data="$BACKUPS/data-$stamp.tgz"
  rm -f "$BACKUPS"/*.part   # недописанное прошлым прогоном, если его прервали

  # Сначала во временный файл: оборванная копия не должна вытеснить целые при ротации
  if ! docker exec campus-db pg_dump -U campus -d campus -Fc > "$dump.part" || [[ ! -s "$dump.part" ]]; then
    rm -f "$dump.part"
    say "ОШИБКА: pg_dump не удался — контейнер campus-db запущен?" >&2
    return 1
  fi
  # Оглавление читается — значит, это архив pg_dump, а не пустышка или текст ошибки
  if ! docker exec -i campus-db pg_restore -l < "$dump.part" > /dev/null; then
    rm -f "$dump.part"
    say "ОШИБКА: копия базы не читается pg_restore" >&2
    return 1
  fi
  mv -f "$dump.part" "$dump"
  chmod 600 "$dump"

  # Справки без базы бесполезны, база без справок отдаёт 410 на проверке QR — сохраняем обе
  if docker exec campus-app tar -czf - -C /data . > "$data.part"; then
    mv -f "$data.part" "$data"
    chmod 600 "$data"
  else
    rm -f "$data.part"
    say "ВНИМАНИЕ: том /data не сохранён — контейнер campus-app не запущен?" >&2
  fi

  rotate 'campus-*.dump'
  rotate 'data-*.tgz'
  say "Копия готова: $(basename "$dump") ($(du -h "$dump" | cut -f1)), всего копий базы: $(ls -1 "$BACKUPS"/campus-*.dump | wc -l)"
}

up() {
  # После перезагрузки dockerd поднимается не сразу — ждём его до двух минут
  for _ in $(seq 1 24); do
    docker info > /dev/null 2>&1 && break
    sleep 5
  done
  # Образ не собираем: на 1 ГБ памяти сборка не влезет, образ привозит deploy_vps.sh
  docker compose --profile vps up -d --no-build
  say "Контейнеры подняты"
}

install() {
  [[ "$(id -u)" -eq 0 ]] || { echo "Запускайте под root: задания пишутся в $CRON_FILE"; exit 1; }
  command -v docker > /dev/null || { echo "Docker не найден — сначала bash scripts/deploy_vps.sh"; exit 1; }
  [[ -f docker-compose.yml ]] || { echo "Нет docker-compose.yml в $DIR"; exit 1; }

  if [[ ! -d /etc/cron.d ]] || ! command -v cron > /dev/null; then
    echo "==> Ставлю cron"
    apt-get update -q > /dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -yq cron > /dev/null
  fi
  systemctl enable --now cron > /dev/null 2>&1 || true

  mkdir -p "$BACKUPS"
  chmod 700 "$BACKUPS"

  echo "==> Задания cron: $CRON_FILE"
  # Во временный файл и mv: cron не должен прочитать файл наполовину записанным
  cat > "$CRON_FILE.tmp" <<CRON
# Кампус: файл пишет scripts/vps_maintenance.sh — правьте скрипт, а не этот файл.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Ночная копия базы и тома /data, хранятся $KEEP последних (время сервера: $(date +%Z))
$BACKUP_AT root bash $DIR/scripts/vps_maintenance.sh backup >> $LOG 2>&1

# Подстраховка после перезагрузки. Обычно контейнеры поднимает restart: unless-stopped,
# но остановленные вручную он не трогает
@reboot root bash $DIR/scripts/vps_maintenance.sh up >> $LOG 2>&1
CRON
  chmod 644 "$CRON_FILE.tmp"
  mv -f "$CRON_FILE.tmp" "$CRON_FILE"
  sed 's/^/    /' "$CRON_FILE"

  echo "==> Первая копия — проверка, что задание сработает ночью"
  backup
  ls -lh "$BACKUPS"
  echo "Готово. Журнал заданий: $LOG"
}

case "${1:-install}" in
  install) install ;;
  backup) backup ;;
  up) up ;;
  *) echo "Использование: bash scripts/vps_maintenance.sh [install|backup|up]"; exit 2 ;;
esac
