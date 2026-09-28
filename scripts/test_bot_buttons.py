#!/usr/bin/env python
"""Проверка кнопки «Открыть …» под сообщениями бота и приёма вебхука — без сети.

Вызовы Bot API подменяются заглушкой, которая записывает тело запроса и по
сценарию отвечает успехом или ошибкой MAX. Проверяется то, что не видно
из смоук-теста (уведомления тестовым id не уходят вовсе):
  • кнопка open_app несёт обязательное поле web_app (имя бота) и payload
    с экраном — `req_<номер>` открывает саму заявку (решение 058);
  • цепочка open_app → ссылка → текст (решение 054) не сломалась, и ссылка
    ведёт на тот же экран через WebAppStartParam;
  • параметр не по формату MAX не отправляется и не роняет сообщение;
  • имя бота без настройки берётся из GET /me один раз;
  • вебхук: после верного секрета от MAX запрос без заголовка отклоняется, и это
    переживает рестарт; ответ бота уходит после коммита в базу; апдейты без
    подтверждённого секрета ограничены, а имя из них не переписывает профиль
    (решение 077). Смоук этого не проверит: апдейт с настоящим id — это
    сообщение живому человеку от настоящего бота.

Запуск (нужны зависимости бэкенда):
  docker compose exec -T app python - < scripts/test_bot_buttons.py
  backend/.venv/Scripts/python scripts/test_bot_buttons.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

# Из репозитория — backend рядом; в контейнере он уже в PYTHONPATH
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
except NameError:
    pass

from app.api import routes_public  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.limits import SlidingWindow  # noqa: E402
from app.integrations.max import client, webhook  # noqa: E402
from app.integrations.max.client import MaxApiError  # noqa: E402
from app.modules.notify import service  # noqa: E402

# Предупреждения клиента о понижении кнопки ожидаемы — не мешаем ими выводу
logging.disable(logging.CRITICAL)

USER = 12345678
REQ = "req_2026-000123"
PUBLIC_URL = "https://campus.example.ru"

passed = 0
failed = 0


def check(title: str, condition: bool, detail: str = "") -> bool:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [ OK ] {title}")
    else:
        failed += 1
        print(f"  [FAIL] {title}" + (f" — {detail}" if detail else ""))
    return condition


class FakeMax:
    """Подмена max_client: отвечает по очереди из `replies` (None — успех)."""

    def __init__(self, replies: list[MaxApiError | None] | None = None, me: object = None):
        self.replies = list(replies or [])
        self.me = me
        self.sent: list[dict] = []
        self.me_calls = 0

    async def send_message(self, user_id, text, attachments=None, notify=True):
        self.sent.append({"user_id": user_id, "text": text, "attachments": attachments})
        reply = self.replies.pop(0) if self.replies else None
        if reply is not None:
            raise reply
        return {"message": {}}

    async def answer_callback(self, callback_id, notification=None, message=None):
        self.sent.append({"callback_id": callback_id, "attachments": None})
        return {}

    async def get_me(self):
        self.me_calls += 1
        if isinstance(self.me, Exception):
            raise self.me
        return self.me

    def button(self, i: int) -> dict | None:
        att = self.sent[i]["attachments"]
        return att[0]["payload"]["buttons"][0][0] if att else None


def fresh(fake: FakeMax, username: str = "t355_hakaton_max_bot") -> FakeMax:
    client.max_client = fake
    client._open_app_supported = True
    client._bot_username = None
    settings.MAX_BOT_USERNAME = username
    return fake


def link_query(button: dict | None) -> dict[str, list[str]]:
    return parse_qs(urlsplit((button or {}).get("url", "")).query)


# ── Вебхук ────────────────────────────────────────────────────────


class FakeRequest:
    def __init__(self, secret: str | None = None):
        self.headers = {"X-Max-Bot-Api-Secret": secret} if secret else {}


def restart_guard() -> None:
    """Как после рестарта процесса: отметка о секрете читается с диска заново."""
    routes_public._secret_confirmed = None


class FakeSession:
    """Сессия базы для handle_update: запоминает, сколько сообщений ушло к коммиту."""

    def __init__(self, fake: FakeMax, app_user: object = None):
        self.fake = fake
        self.app_user = app_user
        self.sent_at_commit: list[int] = []

    async def execute(self, _stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self.app_user)

    def add(self, obj):
        self.app_user = obj

    async def flush(self):
        pass

    async def commit(self):
        self.sent_at_commit.append(len(self.fake.sent))


_real_touch_user = webhook._touch_user
touched: list[tuple[int, bool]] = []


async def fake_touch_user(session, max_user_id, user, trusted=False):
    touched.append((max_user_id, trusted))


async def fake_is_bound(session, max_user_id):
    return False


def fresh_webhook(fake: FakeMax) -> FakeMax:
    fresh(fake)
    webhook.max_client = fake
    webhook._seen.clear()
    webhook._unverified_updates = SlidingWindow(30, 60)
    webhook._unverified_replies = SlidingWindow(5, 600)
    webhook._touch_user = fake_touch_user
    webhook._is_bound = fake_is_bound
    touched.clear()
    return fake


_mid = 0


def started(user_id: object, update_type: str = "bot_started") -> dict:
    global _mid
    _mid += 1
    return {"update_type": update_type, "user": {"user_id": user_id, "first_name": "Анна"},
            "message": {"body": {"mid": f"mid-{_mid}"}}}


async def main() -> None:
    settings.MINIAPP_PUBLIC_URL = PUBLIC_URL
    if not settings.LINK_SECRET and not settings.MAX_BOT_TOKEN:
        settings.LINK_SECRET = "test-link-secret"

    print("1. open_app принят")
    fake = fresh(FakeMax())
    await client.send_with_app_button(USER, "Статус", "Открыть заявку", payload=REQ)
    check("одно сообщение, кнопка open_app с web_app и payload",
          len(fake.sent) == 1 and fake.button(0) == {
              "type": "open_app", "text": "Открыть заявку",
              "web_app": "t355_hakaton_max_bot", "payload": REQ},
          str(fake.sent))

    print("2. Приложение не привязано: ошибка про webApp")
    fake = fresh(FakeMax([MaxApiError(400, "Field 'webApp' cannot be null")]))
    await client.send_with_app_button(USER, "Статус", "Открыть заявку", payload=REQ)
    q = link_query(fake.button(1) if len(fake.sent) > 1 else None)
    check("со второй попытки — кнопка-ссылка на ту же заявку со входом",
          len(fake.sent) == 2 and fake.button(1)["type"] == "link"
          and q.get("WebAppStartParam") == [REQ] and bool(q.get("lt")),
          str(fake.sent)[:300])
    check("open_app выключен для следующих сообщений", client.open_app_supported() is False)
    await client.send_with_app_button(USER, "Ещё", "Открыть заявку", payload=REQ)
    check("следующее сообщение — сразу ссылкой", len(fake.sent) == 3 and fake.button(2)["type"] == "link")

    print("3. Другой отказ 4xx")
    fake = fresh(FakeMax([MaxApiError(400, "payload is invalid")]))
    await client.send_with_app_button(USER, "Статус", "Открыть заявку", payload=REQ)
    check("сообщение ушло ссылкой, open_app для следующих остался",
          len(fake.sent) == 2 and fake.button(1)["type"] == "link" and client.open_app_supported())

    print("4. Сбой MAX 5xx")
    fake = fresh(FakeMax([MaxApiError(502, "bad gateway")]))
    try:
        await client.send_with_app_button(USER, "Статус", "Открыть заявку", payload=REQ)
        raised = False
    except MaxApiError:
        raised = True
    check("исключение уходит в очередь на повтор, ссылкой не шлём", raised and len(fake.sent) == 1)

    print("5. Не прошла и ссылка")
    fake = fresh(FakeMax([MaxApiError(400, "webApp"), MaxApiError(400, "bad url")]))
    await client.send_with_app_button(USER, "Статус", "Открыть заявку", payload=REQ)
    check("третья попытка — просто текст", len(fake.sent) == 3 and fake.sent[2]["attachments"] is None)

    print("6. Параметр не по формату MAX")
    fake = fresh(FakeMax([MaxApiError(400, "webApp")]))
    await client.send_with_app_button(USER, "Статус", "Открыть заявку", payload="req_№1 2")
    check("open_app без payload", "payload" not in (fake.button(0) or {}), str(fake.button(0)))
    check("ссылка без WebAppStartParam, но со входом",
          "WebAppStartParam" not in link_query(fake.button(1)) and bool(link_query(fake.button(1)).get("lt")))

    print("7. Пересылаемое сообщение (signed=False)")
    fake = fresh(FakeMax([MaxApiError(400, "webApp")]))
    await client.send_with_app_button(USER, "Событие", "Открыть событие", signed=False, payload="event_7")
    q = link_query(fake.button(1))
    check("ссылка без токена входа, но на событие", "lt" not in q and q.get("WebAppStartParam") == ["event_7"],
          fake.button(1)["url"])

    print("8. Имя бота не задано — GET /me")
    fake = fresh(FakeMax(me={"username": "some_bot", "user_id": 1}), username="")
    await client.send_with_app_button(USER, "A", "Открыть", payload=REQ)
    await client.send_with_app_button(USER, "B", "Открыть", payload=REQ)
    check("web_app из /me, запрос один на оба сообщения",
          fake.button(0)["web_app"] == "some_bot" and fake.button(1)["web_app"] == "some_bot"
          and fake.me_calls == 1, f"me_calls={fake.me_calls}")

    fake = fresh(FakeMax(me=MaxApiError(503, "down")), username="")
    await client.send_with_app_button(USER, "A", "Открыть", payload=REQ)
    check("/me недоступен — сообщение всё равно уходит ссылкой",
          len(fake.sent) == 1 and fake.button(0)["type"] == "link")
    fake.me = {"username": "some_bot"}
    await client.send_with_app_button(USER, "B", "Открыть", payload=REQ)
    check("неудачу не запомнили: следующее спросило /me снова и ушло с open_app",
          fake.me_calls == 2 and fake.button(1)["type"] == "open_app")

    print("9. Очередь уведомлений передаёт payload")
    fake = fresh(FakeMax())
    item = SimpleNamespace(
        max_user_id=USER, kind="REQUEST_STATUS", text="Статус",
        payload_json={"open_app_label": "Открыть заявку", "open_app_payload": REQ},
    )
    await service._deliver(item)
    check("уведомление о заявке — open_app с req_<номер>",
          fake.button(0) is not None and fake.button(0).get("payload") == REQ, str(fake.sent))

    print("10. Секрет вебхука подтверждает сам MAX (решение 077)")
    # Отметка — во временной папке: в контейнере DATA_DIR — настоящий том /data
    settings.DATA_DIR = tempfile.mkdtemp(prefix="campus-webhook-")
    settings.MAX_WEBHOOK_SECRET = "test-secret-1"
    settings.MAX_WEBHOOK_REQUIRE_SECRET = False
    restart_guard()
    check("пока MAX секрет не присылал — без заголовка принят, но не подтверждён",
          routes_public._check_webhook_secret(FakeRequest()) == (True, False))
    check("чужой секрет — отказ", routes_public._check_webhook_secret(FakeRequest("wrong")) == (False, False))
    check("верный секрет — принят и подтверждён",
          routes_public._check_webhook_secret(FakeRequest("test-secret-1")) == (True, True))
    check("отметка записана в DATA_DIR", routes_public._secret_mark_path().exists())
    check("после верного секрета без заголовка — отказ",
          routes_public._check_webhook_secret(FakeRequest()) == (False, False))
    restart_guard()
    check("отметка переживает рестарт", routes_public._check_webhook_secret(FakeRequest()) == (False, False))
    settings.MAX_WEBHOOK_SECRET = "test-secret-2"
    restart_guard()
    check("новый секрет сбрасывает отметку",
          routes_public._check_webhook_secret(FakeRequest()) == (True, False))
    settings.MAX_WEBHOOK_REQUIRE_SECRET = True
    check("MAX_WEBHOOK_REQUIRE_SECRET=true — без заголовка отказ и без отметки",
          routes_public._check_webhook_secret(FakeRequest()) == (False, False))
    settings.MAX_WEBHOOK_REQUIRE_SECRET = False

    print("11. Апдейт: коммит до запросов к MAX, лимиты без подтверждённого секрета")
    settings.MAX_BOT_TOKEN = settings.MAX_BOT_TOKEN or "test-token"
    fake = fresh_webhook(FakeMax())
    session = FakeSession(fake)
    await webhook.handle_update(session, started(USER))
    check("приветствие ушло одно, и соединение с базой отпущено до него",
          len(fake.sent) == 1 and session.sent_at_commit == [0],
          f"sent={len(fake.sent)}, commit при {session.sent_at_commit}")

    fake = fresh_webhook(FakeMax())
    await webhook.handle_update(FakeSession(fake), started(900123))
    check("тестовому id ответ не отправляется", fake.sent == [] and touched == [(900123, False)])

    fake = fresh_webhook(FakeMax())
    for _ in range(7):
        await webhook.handle_update(FakeSession(fake), started(22222222))
    check("без подтверждённого секрета — не больше 5 ответов одному id за 10 минут",
          len(fake.sent) == 5, f"ушло {len(fake.sent)}")

    fake = fresh_webhook(FakeMax())
    for _ in range(7):
        await webhook.handle_update(FakeSession(fake), started(22222222), verified=True)
    check("с верным секретом ответы не ограничены", len(fake.sent) == 7, f"ушло {len(fake.sent)}")

    fake = fresh_webhook(FakeMax())
    for i in range(35):
        await webhook.handle_update(FakeSession(fake), started(30000000 + i))
    check("без подтверждённого секрета — не больше 30 апдейтов в минуту",
          len(touched) == 30, f"обработано {len(touched)}")

    fake = fresh_webhook(FakeMax())
    await webhook.handle_update(FakeSession(fake), started("12345678"))
    await webhook.handle_update(FakeSession(fake), {"update_type": "bot_started", "user": ["x"]})
    check("id не числом и пользователь не объектом — апдейт пропущен", touched == [] and fake.sent == [])

    fake = fresh_webhook(FakeMax())
    await webhook.handle_update(
        FakeSession(fake),
        {"update_type": "message_callback",
         "callback": {"callback_id": "cb-1", "payload": "x", "user": {"user_id": USER}}},
        verified=True)
    check("нажатие кнопки — ответ на callback, без сообщения",
          len(fake.sent) == 1 and fake.sent[0].get("callback_id") == "cb-1")

    webhook._touch_user = _real_touch_user
    profile = SimpleNamespace(first_name="Подделка", last_name="Чужая", username="", photo_url="")
    maxuser = {"user_id": USER, "first_name": "Анна", "last_name": "", "username": "anna"}
    await webhook._touch_user(FakeSession(fake, profile), USER, maxuser, trusted=False)
    check("апдейт без подтверждённого секрета имя в профиле не меняет",
          profile.first_name == "Подделка" and profile.last_name == "Чужая")
    await webhook._touch_user(FakeSession(fake, profile), USER, maxuser, trusted=True)
    check("апдейт с верным секретом переписывает имя из профиля MAX",
          (profile.first_name, profile.last_name, profile.username) == ("Анна", "", "anna"),
          str(profile))

    print(f"\nуспешно: {passed}, провалено: {failed}")
    sys.exit(1 if failed else 0)


asyncio.run(main())
