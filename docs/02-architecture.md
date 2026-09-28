# Архитектура бэкенда

> **Это проект, написанный до кода.** Идеи и контракты в силе, но часть решений
> при реализации упростили — меньше сервисов, меньше мест, где что-то не поднимется.
> Как устроено на самом деле — README («Архитектура», «Структура репозитория»)
> и журнал решений. Главные расхождения:
>
> | В проекте ниже | В коде |
> |---|---|
> | Alembic | Миграций нет: `create_all` при старте и идемпотентные `ALTER` (`main.py`) |
> | ARQ + Redis | Фоновые задачи — asyncio-циклы в процессе приложения (`workers/scheduler.py`), очередь сообщений — таблица `outbox` в Postgres |
> | Кеш initData в Redis | Словарь в памяти процесса на 5 минут (`core/deps.py`) |
> | TTL initData 15 минут | Час (решение 052) |
> | S3/MinIO | Том `/data` контейнера |
> | WeasyPrint | fpdf2 + шрифт PT Sans: чистый Python, без системных библиотек (шапка `modules/requests/pdf.py`) |
> | Модули `routes/service/repo` | Роуты в `api/`, логика в `modules/*/` |
> | Запасные эмбеддинги e5 по `EMBEDDING_PROVIDER` | Не реализованы: только Yandex, вектор 256 (решения 018, 021) |
> | Время по Иркутску в коде | `UNIVERSITY_TZ_HOURS` и `UNIVERSITY_NAME` в настройках (решение 066) |

Стек (реализация): **Python + FastAPI (async) · PostgreSQL 16 + pgvector · SQLAlchemy 2 · fpdf2 · Yandex AI Studio**

---

## Структура проекта

```
backend/
├─ app/
│  ├─ main.py                  FastAPI, роутеры, lifespan
│  ├─ core/
│  │  ├─ config.py             pydantic-settings
│  │  ├─ security.py           validate_init_data, зависимости ролей
│  │  └─ deps.py               get_current_student, get_staff
│  ├─ db/
│  │  ├─ models/               SQLAlchemy
│  │  └─ session.py
│  ├─ modules/
│  │  ├─ binding/              routes · service · repo
│  │  ├─ requests/             + engine.py (шаблоны, ФСМ) · pdf.py
│  │  ├─ calendar/
│  │  ├─ opportunities/
│  │  ├─ matching/
│  │  └─ assistant/
│  │     ├─ tools.py           функции-инструменты
│  │     ├─ rag.py             чанкинг, эмбеддинги, гибридный поиск
│  │     ├─ prompts.py
│  │     └─ service.py
│  ├─ integrations/max/
│  │  ├─ client.py             send_message, send_document, uploads
│  │  └─ webhook.py
│  └─ workers/
│     ├─ outbox.py             пуши, rate limit 30 rps, бэкофф
│     ├─ reminders.py          события 24ч/1ч, дедлайны 7/2 дня
│     ├─ buddy.py
│     └─ indexer.py            эмбеддинги базы знаний
├─ alembic/
├─ seed/
└─ tests/
```

Каждый модуль — тройка `routes.py / service.py / repo.py`. Предсказуемо: любой в команде
открывает чужой модуль и сразу понимает, где что.

---

## Авторизация

Каждый запрос из мини-апки несёт заголовок:
```
Authorization: MaxInitData <raw initData string>
```

Один middleware (не размазывать по хендлерам):
1. Парсит `WebAppData` (см. `03-max-platform.md`)
2. Считает HMAC, сравнивает constant-time
3. Проверяет `auth_date`, TTL час (`INIT_DATA_TTL_SECONDS`, решение 052)
4. Кладёт в контекст: `max_user_id`, `chat_id`, `chat_type`, `student_id`, `role`

Кешировать результат валидации в Redis на 5 минут по хешу строки — иначе HMAC считается
на каждый запрос списка.

```python
import hmac, hashlib, time
from urllib.parse import parse_qsl

def validate_init_data(raw: str, bot_token: str, ttl_seconds: int = 900) -> dict:
    pairs = dict(parse_qsl(raw, keep_blank_values=True))   # parse_qsl сам делает URL-decode
    received = pairs.pop("hash", None)
    if not received:
        raise ValueError("no hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated, received):
        raise ValueError("bad signature")
    if time.time() - int(pairs["auth_date"]) > ttl_seconds:
        raise ValueError("expired")
    return pairs
```

## Привязка MAX ↔ студент

**Первое, что пишется.** `initData` даёт `max_user_id`; справка нужна «Иванову, Б-20-1, зачётка 12345».
Моста нет — строится явно.

```
POST /api/binding/claim  { code: "A7K2-9M" }
  → binding_code (проверить expires_at, used_at)
  → создать binding(app_user_id, student_id)
  → вернуть профиль
```

Коды генерятся скриптом из справочника `student`. Лимит попыток: **5 в час на пользователя**,
иначе код брутфорсится за минуту.

Защищённые эндпоинты без привязки отдают `409 BINDING_REQUIRED` — фронт по этому коду
показывает онбординг.

## Роли

`STUDENT` · `STAFF_CLERK` · `STAFF_HEAD` · `ORGANIZER` · `MODERATOR` · `ADMIN`
Берётся из таблицы `staff`, **никогда** из запроса.

---

## Схема БД

```sql
-- ЯДРО
student(id, last_name, first_name, middle_name, group_name,
        faculty, course, record_book_no, birth_date)          -- сидируется
app_user(id, max_user_id UNIQUE, first_name, last_name,
         username, photo_url, created_at, last_seen_at)
binding(id, app_user_id UNIQUE, student_id UNIQUE, verified_at, method)
binding_code(code PK, student_id, expires_at, used_at)
staff(id, app_user_id, department_id, role, can_issue text[])

-- ЗАЯВКИ
request_template(key PK, title, icon, schema_json, route_json,
                 doc_template, sla_hours, active)
request(id, public_no UNIQUE, template_key, student_id, payload_json,
        status, assignee_id, department_id, created_at, updated_at, due_at)
request_event(id, request_id, from_status, to_status, actor_id, comment, created_at)
document(id, request_id, uuid UNIQUE, file_key, file_name,
         issued_by, issued_at, valid_until, revoked_at)

-- КАЛЕНДАРЬ
calendar_event(id, title, description, kind, starts_at, ends_at, all_day,
               location, organizer_name, audience_json, capacity,
               registration_required, registration_deadline,
               source, external_id, status, created_by, created_at)
event_registration(id, event_id, student_id, status, created_at)
  -- UNIQUE INDEX (event_id, student_id) WHERE status IN ('REGISTERED','WAITLIST')

-- ВОЗМОЖНОСТИ
opportunity(id, title, kind, description, organizer, level, url,
            registration_deadline, starts_at, ends_at,
            team_size_min, team_size_max, prize_text, tag_ids int[],
            source, author_id, moderation_status, moderated_by, moderated_at, created_at)
opportunity_interest(opportunity_id, student_id, level)   -- INTERESTED | GOING

-- МАТЧИНГ
match_profile(id, app_user_id UNIQUE, bio, is_freshman,
              wants_mentor, wants_mentee, district, visible)
tag(id, kind, title, slug)                                -- SUBJECT|ACTIVITY|SKILL|LOCATION
profile_tag(profile_id, tag_id)
intent(id, author_id, kind, title, description, tag_ids int[],
       opportunity_id NULL, active, expires_at, created_at)
swipe(id, actor_id, intent_id, decision, created_at)      -- UNIQUE(actor_id, intent_id)
match_pair(id, a_user_id, b_user_id, intent_id, created_at, chat_opened_at)

-- АССИСТЕНТ
kb_document(id, title, source_type, source_url, body, version, updated_at, active)
kb_chunk(id, document_id, ord, text, tokens, embedding vector(N),   -- N уточнить до миграции
         tsv tsvector GENERATED)
conversation(id, app_user_id, channel, started_at, last_message_at)
ai_message(id, conversation_id, role, content_json, tool_calls_json,
           input_tokens, output_tokens, latency_ms, created_at)

-- СКВОЗНОЕ
outbox(id, app_user_id, kind, payload_json, dedup_key UNIQUE,
       status, attempts, next_attempt_at, sent_at, error)
notification_pref(app_user_id, kind, enabled)
audit_log(id, actor_id, action, entity_type, entity_id, diff_json, created_at)
```

Первая миграция должна содержать `CREATE EXTENSION vector;`
Образ БД — `pgvector/pgvector:pg16`.

---

## Движок заявок

Валидация `payload` строится из `schema_json` шаблона на лету.
Явный валидатор предпочтительнее динамического `create_model` — проще отлаживается
и умеет свои правила (размер файла, длина).

```python
def validate_payload(fields: list[dict], payload: dict) -> dict:
    errors, clean = {}, {}
    for f in fields:
        name, ftype = f["name"], f["type"]
        val = payload.get(name)
        if val in (None, "", []):
            if f.get("required"):
                errors[name] = "Обязательное поле"
            else:
                clean[name] = f.get("default")
            continue
        match ftype:
            case "select":
                if val not in f["options"]:
                    errors[name] = "Недопустимое значение"
            case "number":
                val = int(val)
                if not (f.get("min", -1e9) <= val <= f.get("max", 1e9)):
                    errors[name] = f"Диапазон {f.get('min')}–{f.get('max')}"
            case "text" | "textarea":
                if len(str(val)) > f.get("maxLength", 1000):
                    errors[name] = "Слишком длинно"
            case "bool":
                val = bool(val)
            case "file":
                if not file_exists_and_owned(val, owner=payload["_student_id"]):
                    errors[name] = "Файл не найден"
        clean[name] = val
    if errors:
        raise ValidationFailed(errors)   # → 422 с пофайловыми ошибками
    return clean
```

Тот же `fields` отдаётся фронту по `GET /api/requests/templates/{key}` — форма рендерится
динамически. Один шаблон — одна правда о полях.

Переходы статусов — только через `RequestService.transition()`: проверка легальности перехода,
проверка роли актора по `route`, запись `request_event`, постановка задачи в `outbox`.
Всё в одной транзакции.

---

## Отправка документа в чат

```python
import httpx

API = "https://platform-api2.max.ru"
HEADERS = {"Authorization": BOT_TOKEN}

async def send_document(user_id: int, path: str, filename: str, text: str):
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(f"{API}/uploads", params={"type": "file"}, headers=HEADERS)
        r.raise_for_status()
        upload_url = r.json()["url"]

        with open(path, "rb") as f:
            up = await c.post(upload_url, files={"data": (filename, f)})
        up.raise_for_status()
        token = up.json()["token"]          # ⚠️ форму ответа проверить на практике

        await c.post(f"{API}/messages", params={"user_id": user_id}, headers=HEADERS,
                     json={"text": text,
                           "attachments": [{"type": "file",
                                            "payload": {"token": token}}]})
```

**Вызывается только из воркера очереди.** Третий шаг регулярно падает сразу после второго
(«медиа ещё обрабатывается») — нужен ретрай с бэкоффом.

---

## Ассистент

### RAG: гибридный поиск обязателен

На базе в 50 документов чистый вектор промахивается мимо точных формулировок
(«пункт 4.2», «форма 26»). Вектор + полнотекст, объединение через RRF:

```sql
WITH vec AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> :qvec) AS rnk
  FROM kb_chunk ORDER BY embedding <=> :qvec LIMIT 30
),
fts AS (
  SELECT id, ROW_NUMBER() OVER (
           ORDER BY ts_rank(tsv, plainto_tsquery('russian', :q)) DESC) AS rnk
  FROM kb_chunk WHERE tsv @@ plainto_tsquery('russian', :q) LIMIT 30
)
SELECT c.id, c.text, c.document_id,
       COALESCE(1.0/(60+vec.rnk), 0) + COALESCE(1.0/(60+fts.rnk), 0) AS score
FROM kb_chunk c
LEFT JOIN vec ON vec.id = c.id
LEFT JOIN fts ON fts.id = c.id
WHERE vec.id IS NOT NULL OR fts.id IS NOT NULL
ORDER BY score DESC LIMIT 5;
```

Чанки 500–800 токенов с перекрытием ~100, резать по заголовкам/абзацам.
Эмбеддинги — Yandex (см. ниже), размерность вектора уточняется тестовым вызовом.

### Tool calling

`student_id` — из ContextVar, **не** из аргументов тула:

```python
from contextvars import ContextVar
current_student: ContextVar[Student] = ContextVar("current_student")

@beta_async_tool
async def get_my_requests(status: str | None = None) -> str:
    """Заявки текущего студента и их статусы.

    Args:
        status: фильтр — SUBMITTED, IN_REVIEW, SIGNING, READY, ISSUED.
    """
    student = current_student.get()        # ← модель не может подделать
    rows = await repo.list_requests(student.id, status)
    return json.dumps([r.brief() for r in rows], ensure_ascii=False)
```

### Провайдер: Yandex Foundation Models

Ключ выдан пользователем. Интерфейс всё равно держим абстрактным:

```python
class LLMProvider(Protocol):
    async def chat(self, *, messages, tools, system) -> ChatResult: ...
    async def embed(self, texts: list[str], kind: str) -> list[list[float]]: ...
```

**Используем OpenAI-совместимый эндпоинт, не нативный** (решение 017):

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key=settings.YC_API_KEY,
    base_url="https://ai.api.cloud.yandex.net/v1",
    default_headers={"OpenAI-Project": settings.YC_FOLDER_ID},
)

resp = await client.chat.completions.create(
    model=f"gpt://{settings.YC_FOLDER_ID}/yandexgpt/latest",
    messages=messages,
    tools=tools,              # стандартный формат [{"type":"function","function":{...}}]
    tool_choice="auto",
)
```

Авторизация — `Authorization: Api-Key <ключ>` (SDK ставит сам), плюс заголовок
`OpenAI-Project: <folder_id>`. **Без `folder_id` не работает ничего** — он входит
и в `modelUri`, и в заголовок.

Модели: `yandexgpt/latest` (Pro) для диалога, `yandexgpt-lite/latest` для дешёвых
операций — классификация интента, реранк, суммаризация истории.

**Запасной путь — нативный эндпоинт** `POST /foundationModels/v1/completion`,
если OpenAI-совместимый подведёт. Схема другая:
- запрос: `modelUri`, `completionOptions`, `messages`, `tools[].function{name,description,parameters}`
- сообщение содержит ровно одно из: `text` | `toolCallList` | `toolResultList`
- модель зовёт инструмент → `toolCallList.toolCalls[].functionCall {name, arguments}`
- ответ инструмента → `toolResultList.toolResults[].functionResult {name, content}`
- признак вызова: статус альтернативы `ALTERNATIVE_STATUS_TOOL_CALLS` (5)

⚠️ Особенности YandexGPT, которые влияют на код:
- **Нет prompt caching** — экономить на стабильном префиксе нечем. Следствие: держать
  системный промпт и описания тулов компактными, историю диалога агрессивно обрезать.
- Есть `reasoningOptions.mode` — включает внутренние рассуждения, совместимо с tools.
- Документация переехала на `aistudio.yandex.ru`, старые ссылки на
  `yandex.cloud/docs/foundation-models` редиректят туда.

### Эмбеддинги

Тем же ключом, эндпоинт `foundationModels/v1/textEmbedding`.
Две разные модели — **это не опечатка, их нельзя путать**:
- `text-search-doc/latest` — для чанков при индексации
- `text-search-query/latest` — для пользовательского запроса при поиске

✅ **Размерность подтверждена тестовым вызовом — 256**, столбец `vector(256)` в
`kb_chunk` (решение 021). Менять её после наполнения базы больно.

*Причина выбора против локальных эмбеддингов:* снимает 1–2 ГБ RAM с деплоя и убирает
риск «модель не влезла на VPS». Запасной вариант (`multilingual-e5-base`, 768)
**не реализован**: переменная `EMBEDDING_PROVIDER` в `.env.example` зарезервирована
и кодом не читается.

---

## Контракты API

| Метод | Путь | Кто | Описание |
|---|---|---|---|
| `POST` | `/api/binding/claim` | любой | Привязка по коду |
| `GET` | `/api/me` | student | Профиль, роли, флаги |
| `GET` | `/api/requests/templates` | student | Список шаблонов |
| `GET` | `/api/requests/templates/{key}` | student | Схема полей для формы |
| `POST` | `/api/requests` | student | Подать (`Idempotency-Key`) |
| `GET` | `/api/requests` | student | Мои заявки |
| `GET` | `/api/requests/{id}` | student | Детали + история статусов |
| `POST` | `/api/requests/{id}/cancel` | student | Отмена |
| `POST` | `/api/requests/{id}/info` | student | Ответ на `NEEDS_INFO` |
| `GET` | `/api/staff/requests` | staff | Очередь: фильтры, просрочка |
| `POST` | `/api/staff/requests/{id}/transition` | staff | Смена статуса |
| `POST` | `/api/staff/requests/{id}/issue` | staff | Выдать → PDF в чат |
| `GET` | `/verify/{uuid}` | публично | Проверка подлинности |
| `GET` | `/api/events` | student | Календарь под аудиторию |
| `POST` | `/api/events/{id}/register` | student | Запись / вейтлист |
| `DELETE` | `/api/events/{id}/register` | student | Отмена |
| `POST` | `/api/staff/events` | organizer | Создать событие |
| `GET` | `/api/opportunities` | student | Лента с рекомендациями |
| `POST` | `/api/opportunities` | student | Предложить (→ `PENDING`) |
| `POST` | `/api/opportunities/{id}/interest` | student | Отметить интерес |
| `POST` | `/api/opportunities/{id}/looking-for-team` | student | → создаёт интент |
| `GET` | `/api/moderation/queue` | moderator | Очередь UGC |
| `POST` | `/api/moderation/{id}/decide` | moderator | Одобрить / отклонить |
| `GET` | `/api/match/deck` | student | Колода интентов |
| `POST` | `/api/match/swipe` | student | Свайп |
| `GET` | `/api/match/matches` | student | Мои матчи |
| `POST` | `/api/match/intents` | student | Создать интент |
| `POST` | `/api/assistant/message` | student | Вопрос ассистенту (SSE-стрим) |
| `GET` | `/api/assistant/history` | student | История диалога |
| `POST` | `/webhook/max` | MAX | Вебхук бота |

Ошибки единым конвертом: `{ "error": { "code", "message", "details"? } }`
Коды: `BINDING_REQUIRED` · `FORBIDDEN` · `VALIDATION_FAILED` · `EVENT_FULL` ·
`ALREADY_SWIPED` · `RATE_LIMITED`

**Типы для фронта:** `curl /openapi.json | npx openapi-typescript -o src/shared/api/types.ts`

---

## Фоновые задачи (ARQ)

| Джоб | Расписание | Что делает |
|---|---|---|
| `outbox-worker` | непрерывно | Отправка пушей, ретраи, rate limit 30 rps |
| `event-reminders` | каждые 5 мин | События через 24 ч и 1 ч → outbox |
| `deadline-reminders` | раз в сутки | Дедлайны возможностей за 7 и 2 дня |
| `intent-expiry` | раз в сутки | Гасит протухшие интенты |
| `buddy-matcher` | раз в час | Подбор наставников новым первокурсникам |
| `kb-indexer` | по событию | Чанкинг + эмбеддинги при изменении документа |
| `sla-watchdog` | раз в час | Просроченные заявки → уведомление деканату |

Kinds для outbox: `REQUEST_STATUS` · `DOCUMENT_ISSUED` · `EVENT_REMINDER` ·
`WAITLIST_PROMOTED` · `OPPORTUNITY_DEADLINE` · `MATCH_FOUND` · `BUDDY_ASSIGNED` · `ESCALATION_ANSWERED`

Тихие часы: не слать с 22:00 до 08:00, переносить на утро.

---

## Вебхук бота

```python
@router.post("/webhook/max")
async def webhook(request: Request):
    body = await request.json()
    if not verify_source(request):        # секрет в пути или заголовке
        raise HTTPException(403)
    if await seen_before(body):           # дедуп по update/message id, Redis SETNX + TTL
        return {"ok": True}
    await queue.enqueue("handle_update", body)
    return {"ok": True}                   # ← 200 за <200 мс, всегда
```

1. Отвечать 200 сразу — иначе таймаут → ретрай → дубли сообщений пользователю
2. Дедупликация обязательна — повторная доставка случается
3. Порядок апдейтов не гарантирован
4. Ошибка обработки не должна возвращать 5xx — иначе MAX ретраит вечно

---

## Python-специфичные грабли

| Грабля | Последствие | Решение |
|---|---|---|
| Синхронный код в async-хендлере | Сервер встаёт на время инференса | `run_in_threadpool` или вынос в ARQ-воркер |
| Модель эмбеддингов в памяти | ~1–2 ГБ RAM, сервис не поднимется на малом VPS | Отдельный контейнер / квантованная модель / загрузка в lifespan |
| `uvicorn --workers N` | N копий модели в памяти | 1 воркер API + отдельный процесс индексации |
| Alembic autogenerate | Молча пропускает изменения индексов и enum | Читать сгенерённую миграцию глазами |
| pgvector | Не включён по умолчанию | `CREATE EXTENSION vector;` в первой миграции |
| Наивный rate limit | 429 от MAX, потеря пушей | Токен-бакет 30 rps в воркере |

---

## Сквозные требования

- **Идемпотентность** на всех мутациях: заголовок `Idempotency-Key`, таблица ключей на 24 ч.
  Мобильная сеть отваливается, пользователь жмёт второй раз — заявка задваивается.
- **Аудит** действий сотрудников (`audit_log`) — кто выдал справку. Вопрос зададут.
- **Feature-флаги** в конфиге — за день до сдачи недоделанное выключается строкой.
