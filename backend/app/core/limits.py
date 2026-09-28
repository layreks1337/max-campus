"""Ограничители частоты и размера запросов.

Всё в памяти процесса: сервис один, рестарт обнуляет счётчики — для защиты
публичного стенда от скрипта этого достаточно (как и у лимита вопросов
ассистенту). Ключ — что угодно хешируемое: id пользователя, адрес клиента.
"""

from __future__ import annotations

import ipaddress
import json
import time
from collections import defaultdict, deque
from collections.abc import Hashable

from fastapi import HTTPException, Request

# ── Адрес клиента ─────────────────────────────────────────────────


def _is_internal(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def client_ip(request: Request) -> str | None:
    """Адрес человека, а не прокси. None — запрос пришёл напрямую изнутри.

    На стенде приложение слушает только 127.0.0.1 хоста, снаружи ходят через
    Caddy (профиль vps). Caddy не доверяет присланному клиентом
    X-Forwarded-For и дописывает в конец адрес, с которого пришёл запрос, —
    поэтому берём последний элемент и только если соседом был внутренний адрес.
    Запрос без заголовка с внутреннего адреса — это сам сервер: смоук-тест,
    скрипты обслуживания. Им лимиты по адресу не нужны.
    """
    peer = request.client.host if request.client else ""
    if not _is_internal(peer):
        return peer or None
    forwarded = request.headers.get("x-forwarded-for", "")
    last = forwarded.split(",")[-1].strip()
    return last or None


# ── Скользящее окно ───────────────────────────────────────────────


class SlidingWindow:
    """Не больше `limit` событий за `window` секунд на ключ."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[Hashable, deque[float]] = defaultdict(deque)

    def _trim(self, key: Hashable, now: float) -> deque[float]:
        stamps = self._hits[key]
        while stamps and now - stamps[0] >= self.window:
            stamps.popleft()
        return stamps

    def _cleanup(self, now: float) -> None:
        # Разовая уборка: иначе словарь копит все ключи, что когда-то приходили
        if len(self._hits) > 4096:
            for key in [k for k, q in self._hits.items() if not q or now - q[-1] >= self.window]:
                del self._hits[key]

    def allowed(self, key: Hashable) -> bool:
        """Есть ли место, не занимая его."""
        return len(self._trim(key, time.monotonic())) < self.limit

    def hit(self, key: Hashable) -> None:
        now = time.monotonic()
        self._cleanup(now)
        self._trim(key, now).append(now)

    def forget(self, key: Hashable) -> None:
        self._hits.pop(key, None)

    def take(self, key: Hashable) -> bool:
        """Занять место, если оно есть."""
        if not self.allowed(key):
            return False
        self.hit(key)
        return True


# ── Размер тела запроса ───────────────────────────────────────────


def _too_large_detail(limit: int) -> dict:
    return {
        "code": "PAYLOAD_TOO_LARGE",
        "message": f"Слишком большой запрос: не больше {max(1, limit // (1024 * 1024))} МБ",
    }


class BodyTooLarge(HTTPException):
    """Тело перевалило за лимит посреди чтения. Наследник HTTPException:
    FastAPI пропускает его через разбор формы и JSON, и клиент получает 413
    в общем формате ошибок, а не «не удалось разобрать тело»."""

    def __init__(self, limit: int) -> None:
        super().__init__(status_code=413, detail=_too_large_detail(limit))


class BodySizeLimit:
    """ASGI-слой: тело больше лимита не дочитывается, ответ — 413.

    Без него любой JSON-эндпоинт, включая вебхук без авторизации, читал тело
    целиком в память ещё до проверки прав: запрос на 400 МБ ронял бы сервер
    с 1 ГБ памяти. Content-Length проверяется сразу, тело без него (chunked)
    считается по мере чтения. `limits` — (префикс пути, байт), первый
    подходящий; остальным — `default`.
    """

    def __init__(self, app, *, default: int, limits: tuple[tuple[str, int], ...] = ()) -> None:
        self.app = app
        self.default = default
        self.limits = limits

    def _limit_for(self, path: str) -> int:
        for prefix, limit in self.limits:
            if path.startswith(prefix):
                return limit
        return self.default

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)

        limit = self._limit_for(scope["path"])
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > limit:
                    return await _reject(send, limit)
                break

        received = 0
        started = False

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLarge(limit)
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await _reject(send, limit)


async def _reject(send, limit: int) -> None:
    body = json.dumps({"error": _too_large_detail(limit)}, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
