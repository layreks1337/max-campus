#!/usr/bin/env python
"""Настройка бота: информация о нём и подписка на вебхук.

Использование:
    python scripts/setup_bot.py                 показать состояние
    python scripts/setup_bot.py subscribe URL   подписаться на вебхук
    python scripts/setup_bot.py unsubscribe URL отписаться
    python scripts/setup_bot.py send USER_ID    отправить тестовое сообщение

Требует переменные MAX_BOT_TOKEN и бандл сертификатов Минцифры
(certs/russian_trusted_bundle.pem) — без него TLS до platform-api2 не поднимется.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru")
BUNDLE = ROOT / "certs" / "russian_trusted_bundle.pem"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV = load_env()
TOKEN = os.environ.get("MAX_BOT_TOKEN") or ENV.get("MAX_BOT_TOKEN", "")

if not TOKEN:
    print("Не задан MAX_BOT_TOKEN (ни в окружении, ни в .env)")
    sys.exit(1)

CTX = ssl.create_default_context(cafile=str(BUNDLE)) if BUNDLE.exists() else None
if CTX is None:
    print(f"! Бандл сертификатов не найден: {BUNDLE}")
    print("  Запустите: bash scripts/fetch_certs.sh")


def call(method: str, path: str, params: dict | None = None, body: dict | None = None):
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", TOKEN)
    if data:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=40, context=CTX) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def show() -> None:
    status, me = call("GET", "/me")
    print(f"GET /me → {status}")
    if isinstance(me, dict):
        print(f"  бот:      {me.get('name')}")
        print(f"  username: @{me.get('username')}")
        print(f"  user_id:  {me.get('user_id')}")

    status, subs = call("GET", "/subscriptions")
    print(f"\nGET /subscriptions → {status}")
    items = subs.get("subscriptions", []) if isinstance(subs, dict) else []
    if not items:
        print("  подписок нет — бот не получает обновления")
    for s in items:
        print(f"  {s.get('url')}  (обновления: {s.get('update_types') or 'все'})")


def subscribe(url: str) -> None:
    secret = ENV.get("MAX_WEBHOOK_SECRET", "")
    body: dict = {"url": url}
    if secret:
        body["secret"] = secret
    status, res = call("POST", "/subscriptions", body=body)
    print(f"POST /subscriptions → {status}")
    print(f"  {res}")
    if status < 400:
        print(f"\nГотово. Бот шлёт обновления на {url}")


def unsubscribe(url: str) -> None:
    status, res = call("DELETE", "/subscriptions", params={"url": url})
    print(f"DELETE /subscriptions → {status}")
    print(f"  {res}")


def send(user_id: int) -> None:
    body = {
        "text": "Проверка связи. Приложение «Кампус» на связи.",
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {"buttons": [[{"type": "open_app", "text": "Открыть приложение"}]]},
            }
        ],
    }
    status, res = call("POST", "/messages", params={"user_id": user_id}, body=body)
    print(f"POST /messages → {status}")
    print(f"  {res}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "show":
        show()
    elif cmd == "subscribe" and len(sys.argv) > 2:
        subscribe(sys.argv[2])
    elif cmd == "unsubscribe" and len(sys.argv) > 2:
        unsubscribe(sys.argv[2])
    elif cmd == "send" and len(sys.argv) > 2:
        send(int(sys.argv[2]))
    else:
        print(__doc__)
