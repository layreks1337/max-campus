#!/usr/bin/env bash
# Сбрасывает следы прогонов: привязки живых пользователей, заявки, документы,
# свайпы и диалоги ассистента. Справочники, шаблоны и база знаний остаются.
#
# Нужен, когда демонстрацию показывают несколько раз подряд и коды привязки
# должны снова стать доступными.

set -euo pipefail
cd "$(dirname "$0")/.."

CONTAINER="${1:-campus-db}"

# Флаг -i обязателен: без него docker exec не пробрасывает stdin,
# и SQL из heredoc молча уходит в никуда — скрипт «отрабатывает» вхолостую.
docker exec -i "$CONTAINER" psql -U campus -d campus -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;

-- Заявки и всё, что от них зависит
DELETE FROM document;
DELETE FROM request_event;
DELETE FROM request;

-- Активность живых пользователей
DELETE FROM ai_message;
DELETE FROM conversation;
DELETE FROM swipe WHERE actor_user_id IN (SELECT id FROM app_user WHERE max_user_id > 0);
DELETE FROM match_pair;
DELETE FROM event_registration WHERE student_id IN (
  SELECT student_id FROM binding WHERE method <> 'demo-seed'
);
DELETE FROM opportunity_interest WHERE student_id IN (
  SELECT student_id FROM binding WHERE method <> 'demo-seed'
);
DELETE FROM intent WHERE author_user_id IN (SELECT id FROM app_user WHERE max_user_id > 0);

-- Роли и привязки живых пользователей
DELETE FROM staff WHERE app_user_id IN (SELECT id FROM app_user WHERE max_user_id > 0);
DELETE FROM match_profile WHERE app_user_id IN (SELECT id FROM app_user WHERE max_user_id > 0);
DELETE FROM binding WHERE method <> 'demo-seed';
UPDATE binding_code SET used_at = NULL;

-- Очередь уведомлений
DELETE FROM outbox;
DELETE FROM audit_log;

COMMIT;
SQL

echo
echo "Состояние после сброса:"
docker exec "$CONTAINER" psql -U campus -d campus -c "
SELECT 'свободных кодов привязки' AS показатель, count(*)::text AS значение
  FROM binding_code WHERE used_at IS NULL
UNION ALL SELECT 'заявок', count(*)::text FROM request
UNION ALL SELECT 'объявлений в колоде', count(*)::text FROM intent WHERE active
UNION ALL SELECT 'событий', count(*)::text FROM calendar_event
UNION ALL SELECT 'чанков базы знаний', count(*)::text FROM kb_chunk;"

echo "Готово. Коды привязки снова свободны: A7K2-9M, B3N8-4P, C5R1-7T, D9W6-2L"
