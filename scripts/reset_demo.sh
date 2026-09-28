#!/usr/bin/env bash
# Сбрасывает следы прогонов: привязки живых пользователей, заявки, документы,
# свайпы, диалоги ассистента, опросы групп (кроме заложенного сидом) и демо-копии
# студентов (DEMO-*) с их баллами и голосами, тестовые аккаунты (id 900000–999999)
# и файлы справок и вложений на диске. Справочники, шаблоны и база знаний остаются.
#
# Нужен, когда демонстрацию показывают несколько раз подряд и коды привязки
# должны снова стать доступными, а также после смоук-теста и прогона
# scripts/check_data_api.py: всё, что они создают, удаляется здесь.
#
# Аргументы: имя контейнера базы (campus-db) и приложения (campus-app).

set -euo pipefail
cd "$(dirname "$0")/.."

CONTAINER="${1:-campus-db}"
APP_CONTAINER="${2:-campus-app}"

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

-- Демо-копии экспертов (кнопка «Попробовать как студент», зачётка DEMO-<id>)
-- и всё, что на них ссылается. Заявки уже удалены выше.
CREATE TEMP TABLE demo_students ON COMMIT DROP AS
  SELECT id FROM student WHERE record_book_no LIKE 'DEMO-%';
DELETE FROM poll_vote WHERE student_id IN (SELECT id FROM demo_students)
  OR poll_id IN (SELECT id FROM group_poll WHERE author_student_id IN (SELECT id FROM demo_students));
DELETE FROM group_poll WHERE author_student_id IN (SELECT id FROM demo_students);
DELETE FROM group_head WHERE student_id IN (SELECT id FROM demo_students);
DELETE FROM grade_item WHERE student_id IN (SELECT id FROM demo_students);
DELETE FROM event_registration WHERE student_id IN (SELECT id FROM demo_students);
DELETE FROM opportunity_interest WHERE student_id IN (SELECT id FROM demo_students);
DELETE FROM binding_code WHERE student_id IN (SELECT id FROM demo_students);
DELETE FROM binding WHERE student_id IN (SELECT id FROM demo_students);
DELETE FROM student WHERE id IN (SELECT id FROM demo_students);

-- Опросы групп: остаётся только заложенный сидом (самый первый, «Когда удобнее
-- отработка по матанализу?»). Иначе опросы, созданные живыми аккаунтами под
-- кодом старосты (A7K2-9M), видел бы каждый эксперт в «Группа спрашивает».
DELETE FROM poll_vote WHERE poll_id <> (SELECT min(id) FROM group_poll);
DELETE FROM group_poll WHERE id <> (SELECT min(id) FROM group_poll);

-- Тестовые аккаунты (браузерный вход, смоук-тест, scripts/check_data_api.py):
-- id 900000–999999, вход dev:<id>:<Имя>. Их привязки, роли, демо-копии, диалоги
-- и объявления удалены выше; при следующем запросе аккаунт создаётся заново.
-- Автор предложенной возможности остаётся вместе с ней.
DELETE FROM app_user WHERE max_user_id BETWEEN 900000 AND 999999
  AND id NOT IN (SELECT author_user_id FROM opportunity WHERE author_user_id IS NOT NULL);

-- Очередь уведомлений
DELETE FROM outbox;
DELETE FROM audit_log;

COMMIT;
SQL

# PDF справок и вложения заявок: записей о них больше нет, а файлы оставались
# на диске после каждого прогона — смоук и check_data_api.py выдают справки.
DATA_FILES='find /data/documents /data/uploads -type f'
if docker exec "$APP_CONTAINER" true 2>/dev/null; then
  FILES="$(docker exec "$APP_CONTAINER" sh -c "$DATA_FILES 2>/dev/null | wc -l" | tr -d '[:space:]')"
  docker exec "$APP_CONTAINER" sh -c "$DATA_FILES -delete 2>/dev/null || true"
  echo "Файлов справок и вложений удалено: ${FILES:-0}"
else
  echo "ВНИМАНИЕ: контейнер $APP_CONTAINER не запущен — файлы справок в /data не удалены" >&2
fi

echo
echo "Состояние после сброса:"
docker exec "$CONTAINER" psql -U campus -d campus -c "
SELECT 'свободных кодов привязки' AS показатель, count(*)::text AS значение
  FROM binding_code WHERE used_at IS NULL
UNION ALL SELECT 'заявок', count(*)::text FROM request
UNION ALL SELECT 'демо-копий студентов', count(*)::text FROM student WHERE record_book_no LIKE 'DEMO-%'
UNION ALL SELECT 'тестовых аккаунтов', count(*)::text FROM app_user WHERE max_user_id BETWEEN 900000 AND 999999
UNION ALL SELECT 'опросов групп', count(*)::text FROM group_poll
UNION ALL SELECT 'объявлений в колоде', count(*)::text FROM intent WHERE active
UNION ALL SELECT 'событий', count(*)::text FROM calendar_event
UNION ALL SELECT 'чанков базы знаний', count(*)::text FROM kb_chunk;"

echo "Готово. Коды привязки снова свободны: A7K2-9M, B3N8-4P, C5R1-7T, D9W6-2L"
