"""Валидация initData из MAX Bridge.

Алгоритм (см. docs/03-max-platform.md):
  1. URL-decode строки, собрать пары key=value кроме hash
  2. Отсортировать по ключу, склеить через \\n  -> data_check_string
  3. secret    = HMAC_SHA256(key="WebAppData", msg=BotToken)
  4. signature = HMAC_SHA256(key=secret, msg=data_check_string)  -> hex
  5. Сравнить с hash в constant-time, проверить auth_date на TTL
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, unquote

from app.core.config import settings


class InitDataError(Exception):
    """Подпись не сошлась, данные протухли или строка повреждена."""


@dataclass
class MaxUser:
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    photo_url: str = ""

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p).strip()


@dataclass
class InitData:
    user: MaxUser
    chat_id: int | None = None
    chat_type: str = "DIALOG"
    auth_date: int = 0
    start_param: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def _extract_webapp_data(raw: str) -> str:
    """Bridge отдаёт либо голый WebAppData, либо весь фрагмент URL.

    WebAppPlatform и WebAppVersion лежат ВНЕ WebAppData и в подпись не входят —
    если пришла полная строка, вырезаем только нужную часть.
    """
    raw = raw.strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if "WebAppData=" in raw:
        after = raw.split("WebAppData=", 1)[1]
        # отрезаем хвост с платформой/версией, если он есть
        for tail in ("&WebAppPlatform=", "&WebAppVersion="):
            if tail in after:
                after = after.split(tail, 1)[0]
        # значение может быть percent-encoded целиком
        if "=" not in unquote(after).split("&", 1)[0]:
            return after
        return unquote(after) if "%3D" in after or "%26" in after else after
    return raw


def _parse_json_field(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def validate_init_data(
    raw: str,
    bot_token: str | None = None,
    ttl_seconds: int | None = None,
) -> InitData:
    bot_token = bot_token if bot_token is not None else settings.MAX_BOT_TOKEN
    ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.INIT_DATA_TTL_SECONDS

    if not bot_token:
        raise InitDataError("MAX_BOT_TOKEN не задан — валидация невозможна")

    payload = _extract_webapp_data(raw)
    pairs = dict(parse_qsl(payload, keep_blank_values=True))

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("в initData нет поля hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated, received_hash):
        raise InitDataError("подпись initData не сошлась")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("auth_date не число") from exc

    if ttl_seconds > 0 and (time.time() - auth_date) > ttl_seconds:
        raise InitDataError("initData протух")

    return _build(pairs, auth_date)


def _build(pairs: dict[str, str], auth_date: int) -> InitData:
    user_raw = _parse_json_field(pairs.get("user"))
    chat_raw = _parse_json_field(pairs.get("chat"))

    user = MaxUser(
        id=int(user_raw.get("id", 0)),
        first_name=user_raw.get("first_name", "") or "",
        last_name=user_raw.get("last_name", "") or "",
        username=user_raw.get("username", "") or "",
        photo_url=user_raw.get("photo_url", "") or "",
    )
    if not user.id:
        raise InitDataError("в initData нет user.id")

    return InitData(
        user=user,
        chat_id=int(chat_raw["id"]) if chat_raw.get("id") else None,
        chat_type=(chat_raw.get("type") or "DIALOG").upper(),
        auth_date=auth_date,
        start_param=pairs.get("start_param", "") or "",
        raw=pairs,
    )


def parse_dev_auth(raw: str) -> InitData:
    """Режим разработки: `dev:<max_user_id>:<Имя>` — без подписи.

    Работает только при ALLOW_DEV_AUTH=true. Нужен, чтобы открывать приложение
    в обычном браузере, где Bridge недоступен.
    """
    if not settings.ALLOW_DEV_AUTH:
        raise InitDataError("dev-авторизация отключена")
    parts = raw.split(":")
    if len(parts) < 2 or parts[0] != "dev":
        raise InitDataError("некорректный dev-токен")
    try:
        user_id = int(parts[1])
    except ValueError as exc:
        raise InitDataError("dev: id должен быть числом") from exc
    name = parts[2] if len(parts) > 2 else "Dev User"
    return InitData(
        user=MaxUser(id=user_id, first_name=name, username=f"dev{user_id}"),
        auth_date=int(time.time()),
    )
