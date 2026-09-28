# Платформа MAX — факты, ограничения, грабли

Собрано из официальной документации и разборов практиков. Раздел о Bridge сверен
28.09.2026 со страницей `dev.max.ru/docs/webapps/bridge`, самим скриптом
`st.max.ru/js/max-web-app.js` и кодом веб-клиента `web.max.ru`.
**Помеченное ⚠️ проверить на практике в первый день.**

---

## 1. Мини-приложения (WebApps)

### Базовое

- Мини-приложение **не существует автономно** — живёт внутри чат-бота, открывается кнопкой
  типа `open_app` в inline-клавиатуре. Бот обязателен.
- Обязателен HTTPS с сертификатом доверенного УЦ. Самоподписанные не принимаются.
- Bridge подключается скриптом `https://st.max.ru/js/max-web-app.js` → даёт `window.WebApp`.
- **`window.WebApp` есть и вне MAX.** Скрипт создаёт объект всегда. В обычном браузере
  у него `initData` пустой, `platform = null`, а транспорта нет: события теряются с
  `console.warn("[WebApp] Событие не отправлено - транспорт недоступен")`, промисы
  отклоняются только по таймауту — 10 с, у `shareMaxContent`, `shareContent`,
  `downloadFile` 60 с, у `openCodeReader` 10 минут. Поэтому «мы в MAX» — это непустой
  `initData` (`isInsideMax()` в `shared/max.ts`), а не наличие объекта или метода.
- `WebApp.platform` (`ios | android | desktop | web`) приходит во фрагменте адреса
  (`WebAppPlatform`) и в подпись не входит: по нему выбирают, что показать, но не права.
- Ошибка Bridge — `{ error: { code } }`: `client.<метод>.request_timeout` по таймауту,
  `client.unsupported_method.unsupported_method` — метода нет в этом клиенте.

### Чек-лист модерации

- HTTPS
- подключённый Bridge
- работающие `WebApp.ready()` и `BackButton`
- реализованная валидация `initData`

### Bridge API

| Метод / поле | Назначение | Клиенты | У нас |
|---|---|---|---|
| `WebApp.ready()` | Убирает скелетон после отрисовки. Вызывать обязательно | все | `App.tsx` |
| `WebApp.BackButton.show()/hide()/onClick()` | Системная кнопка «Назад» | все | `setBackButton` |
| `WebApp.openLink(url)` | Внешние ссылки | все клиенты MAX; вне MAX — `window.open` | `openExternal` |
| `WebApp.initData` | Подписанная строка для валидации на бэке | все | заголовок `Authorization` |
| `WebApp.initDataUnsafe` | Распарсенный объект. **Для валидации использовать нельзя** | все | — |
| `WebApp.initDataUnsafe.start_param` | Данные из URL (`WebAppStartParam`) — использовать для диплинков | все | `getStartParam` |
| `openCodeReader(fileSelect)` → `{ value }` | Сканер QR; `true` — ещё и выбор снимка из галереи | iOS, Android; web.max.ru — `unsupported_method`; десктоп не описан | проверка билетов (решение 071) |
| `HapticFeedback.impactOccurred / notificationOccurred / selectionChanged` | Вибрация | по документации — кроме веба и десктопа | нажатия и результат проверки билета |
| `requestScreenMaxBrightness()` / `restoreScreenBrightness()` | Яркость на максимум; MAX сам возвращает её через 30 с | iOS, Android; web.max.ru — `unsupported_method` | «Мой билет» |
| `shareMaxContent({ text, link })` → `{ status: shared \| cancelled }` | Окно «Поделиться» самого MAX, нужен клик пользователя | iOS, Android, web.max.ru; десктоп не описан | «Поделиться» событием (решение 072) |
| `shareContent({ text, link })` | Системное окно телефона | iOS, Android; в вебе — `unsupported_method` | не используется |
| `downloadFile(url, name)`, `enableClosingConfirmation()` | Скачивание, подтверждение закрытия | телефоны и веб | не используются: PDF и так приходит в чат |
| `DeviceStorage`, `requestContact`, биометрия, NFC | Хранилище, телефон, вход по отпечатку | по документации — не веб | не используются: нет сценария, а телефон — лишние персональные данные |

Сканер, вибрацию и яркость приложение вызывает только при `platform` = `ios` или
`android`: неизвестный клиент может не ответить вовсе, а библиотека ждёт сканер
10 минут. Без телефона всё это видно встроенным эмулятором клиента: `?maxEmu=android`
(решение 073).

### Структура `InitData`

```
query_id, ip?, auth_date, hash,
user  { id, first_name, last_name, username, language_code, photo_url },
chat  { id, type: DIALOG | CHAT | CHANNEL },
start_param
```

`chat.type` — важный сигнал: апка открыта в личке или в групповом чате. Позволяет делать
контекстные сценарии (например, создание события старостой прямо из чата группы).

### Валидация initData (критично)

Параметры лежат **во фрагменте URL после `#`**, в параметре `WebAppData`.
`WebAppPlatform` и `WebAppVersion` лежат **вне** `WebAppData` и **в хеш не входят**.

Пример URL:
```
https://example.com#WebAppData=chat=...&ip=...&user=...&query_id=...&auth_date=...&hash=<hash>&WebAppPlatform=web&WebAppVersion=26.2.8
```

Алгоритм (идентичен телеграмовскому):
1. URL-decode строки, собрать пары `key=value` кроме `hash`
2. Отсортировать по ключам, склеить через `\n` → `data_check_string`
3. `secret = HMAC_SHA256(key="WebAppData", msg=BotToken)`
4. `signature = HMAC_SHA256(key=secret, msg=data_check_string)`, hex
5. Сравнить с `hash` в constant-time

⚠️ **Порядок аргументов HMAC в документации записан неоднозначно** (`HMAC_SHA256("WebAppData" + BotToken)`).
Если подпись не сходится — поменять местами ключ и сообщение. Проверить на живом initData сразу,
иначе потеря полудня.

⚠️ **Двойной URL-decode ломает значения с `%`.** `parse_qsl` декодирует сам — не декодировать повторно.

**Обязательно:** TTL по `auth_date`. Без него украденный initData вечен. Документация
Bridge рекомендует час; 15 минут, как планировали сначала, мало: подпись выдаётся один раз
при открытии, и сессия умирала посреди сценария (решение 052, `INIT_DATA_TTL_SECONDS=3600`).

---

## 2. Bot API

### Транспорт и авторизация

- Домен: **`https://platform-api2.max.ru`** (не `platform-api`, не `botapi` — оба устарели)
- Требуется **сертификат Минцифры** в списке доверенных
- Токен **только заголовком**: `Authorization: <token>`. Query-параметр больше не поддерживается
- Лимит: **~30 запросов в секунду**
- Вебхуки: только HTTPS, самоподписанные сертификаты не принимаются

### Отправка файла — три шага

Файл **нельзя** передать напрямую в `POST /messages`.

```
1. POST /uploads?type=file          → { url }
   Authorization: <token>

2. POST <url>  multipart/form-data, поле "data"   → { token }   ⚠️ форму ответа проверить

3. POST /messages
   { "text": "...", "attachments": [{"type": "file", "payload": {"token": "<token>"}}] }
```

Типы для `/uploads`: `image` · `file` · `video` · `audio`.
Изображения: до 50 МБ и не более 7680×7680 px (**оба** критерия). Для картинок можно
обойтись внешним URL через `attachments.payload.url`, без `/uploads`.

**Грабли:**
- Старый тип `photo` не работает — теперь `image`
- Отправка сразу после загрузки может упасть: медиа ещё обрабатывается → **нужен retry с задержкой**
- Отсюда следует: отправка файлов возможна **только из очереди**, не из HTTP-хендлера

### Клавиатуры

Клавиатура — **не `reply_markup`**, а вложение в `attachments`:

```json
{"type": "inline_keyboard", "payload": {"buttons": [[{...}, {...}], [{...}]]}}
```

Типы кнопок: `callback` · `link` · `open_app` · `request_geo_location` · `request_contact`

**Лимиты:** до 210 кнопок, до 30 рядов, до 7 кнопок в ряду —
но **не более 3**, если это `link` / `open_app` / `request_geo_location` / `request_contact`.

Отображение: текст центрируется и обрезается по границе; кнопки в ряду равной ширины;
при переполнении включается скролл.

**Кнопка `open_app`** (схема `OpenAppButton`):

```json
{"type": "open_app", "text": "Открыть заявку", "web_app": "t355_hakaton_max_bot", "payload": "req_2026-000123"}
```

- `web_app` — **обязательное** поле, публичное имя бота, к которому привязано мини-приложение.
  Без него MAX отклоняет всё сообщение: `Field 'webApp' cannot be null`.
- `payload` — до 512 символов `[A-Za-z0-9_-]`, приходит в приложение как
  `initDataUnsafe.start_param` — так же, как `startapp` из диплинка `max.ru/<бот>?startapp=…`.
  Тот же параметр MAX кладёт в адрес приложения GET-параметром `WebAppStartParam`.
- У нас: `req_<номер>` — экран заявки, `event_<id>`, `schedule`, `group` и др. — `App.tsx`.
  Запасная кнопка-ссылка передаёт тот же параметр как `?WebAppStartParam=…` (решение 058).
- ⚠️ Поведение живого MAX на кнопку с `web_app` проверяется только сообщением реальному
  пользователю — в локальных тестах Bot API подменён заглушкой (`scripts/test_bot_buttons.py`).

**Грабля:** ID нажавшего кнопку — в `callback.user.user_id`, **не** в отправителе сообщения.

### Callback

Нажатие приходит апдейтом `message_callback`. Ответ — через `POST /answers`.
В ответе поле `message` (NewMessageBody) заменяет сообщение, на котором нажали кнопку.

### SDK

- JS/TS: `max-bot-api-client-ts`, `Keyboard.inlineKeyboard([...])`,
  `Keyboard.button.callback(text, payload)`, `Keyboard.button.link(text, url)`
- Кнопка `open_app` в TS-клиенте появилась отдельным PR — проверить версию пакета
- PHP: `bushlanov-dev/max-bot-api-client-php`
- Rust: `maxbot`
- n8n-нода `pfrankov/n8n-nodes-max` сама переписывает хост на `platform-api2`

---

## 3. Ограничения платформы и риски

| Риск | Суть | Митигация |
|---|---|---|
| ✅ **Публикация** | Размещение ботов и мини-приложений — только для **верифицированных юрлиц РФ** по лицензионному договору | **Снято для хакатона** (FAQ, п. 2): мини-приложение размещается по публичному HTTPS-адресу, ссылка уходит через форму организаторов, привязку к выданному боту выполняют они; регистрация в «MAX для партнёров» не нужна |
| 🟠 **HTTPS** | Обязателен для апки и вебхуков, доверенный УЦ | Стенд — VPS с Caddy и сертификатом Let's Encrypt (решение 048); туннели ngrok и Cloudflare из России ненадёжны |
| 🟠 **Нет DevTools** | На мобильном клиенте отладка вебвью недоступна | Отлаживать в web.max.ru (DevTools браузера) и эмулятором клиента `?maxEmu=android` (решение 073) |
| 🟡 **Сертификат Минцифры** | Нужен для обращений к `platform-api2.max.ru` | Добавить в доверенные на хосте бэкенда |
| 🟡 **Rate limit 30 rps** | Превышение → потеря сообщений | Все исходящие через outbox-очередь с лимитером |

Вопросы, которые стояли перед стартом, и чем закончились:
1. Разметка текста сообщения — сообщения бота уходят простым текстом, без разметки;
   в лимит длины шаблоны не упираются.
2. Чат между двумя пользователями бот не создаёт — контакт в «Откликах» ведёт
   на `max.ru/<username>` собеседника.
3. Long polling не понадобился: и локально, и на стенде работает вебхук.
4. Секрет вебхука есть: передаётся при подписке и приходит заголовком
   `X-Max-Bot-Api-Secret` (решение 053).

---

## 4. Полезные ссылки

- `https://dev.max.ru/docs` — корень документации
- `https://dev.max.ru/docs-api` — справочник API
- `https://dev.max.ru/docs/webapps/introduction` — подключение мини-приложения
- `https://dev.max.ru/docs/webapps/bridge` — Bridge
- `https://dev.max.ru/docs/webapps/validation` — валидация
- `https://dev.max.ru/docs-api/methods/POST/uploads` — загрузка файлов
- `https://dev.max.ru/docs/chatbots/bots-coding/js` — JS SDK
