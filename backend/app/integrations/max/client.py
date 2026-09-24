"""Клиент Bot API мессенджера MAX.

Особенности платформы, заложенные здесь (см. docs/03-max-platform.md):
  • домен platform-api2.max.ru, токен ТОЛЬКО заголовком Authorization
  • TLS требует корневые сертификаты Минцифры — путь в MAX_CA_BUNDLE
  • файл нельзя отправить одним запросом: /uploads -> PUT на выданный URL -> /messages
  • сразу после загрузки отправка может упасть («медиа ещё обрабатывается») -> ретраи
  • лимит ~30 rps -> собственный ограничитель
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger("max.client")


class MaxApiError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"MAX API {status}: {body[:300]}")


class _RateLimiter:
    """Простой токен-бакет, чтобы не упереться в лимит платформы."""

    def __init__(self, rps: float):
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._min_interval:
                await asyncio.sleep(self._min_interval - delta)
            self._last = time.monotonic()


def _build_ssl_context() -> ssl.SSLContext | bool:
    bundle = Path(settings.MAX_CA_BUNDLE)
    if bundle.exists():
        ctx = ssl.create_default_context(cafile=str(bundle))
        return ctx
    log.warning(
        "Бандл сертификатов Минцифры не найден по пути %s — TLS до MAX API, скорее всего, "
        "не поднимется. Скачать: scripts/fetch_certs.sh",
        bundle,
    )
    return True


class MaxClient:
    def __init__(self, token: str | None = None):
        self.token = token if token is not None else settings.MAX_BOT_TOKEN
        self.base = settings.MAX_API_BASE.rstrip("/")
        self._limiter = _RateLimiter(settings.MAX_RATE_LIMIT_RPS)
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=15.0),
                verify=_build_ssl_context(),
                headers={"Authorization": self.token},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, **kw: Any) -> Any:
        await self._limiter.wait()
        client = await self._http()
        url = path if path.startswith("http") else f"{self.base}{path}"
        resp = await client.request(method, url, **kw)
        if resp.status_code >= 400:
            raise MaxApiError(resp.status_code, resp.text)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # ── Информация о боте ─────────────────────────────────────────

    async def get_me(self) -> dict:
        return await self._request("GET", "/me")

    # ── Сообщения ─────────────────────────────────────────────────

    async def send_message(
        self,
        user_id: int,
        text: str,
        attachments: list[dict] | None = None,
        notify: bool = True,
    ) -> dict:
        body: dict[str, Any] = {"text": text, "notify": notify}
        if attachments:
            body["attachments"] = attachments
        return await self._request(
            "POST", "/messages", params={"user_id": user_id}, json=body
        )

    async def answer_callback(
        self, callback_id: str, notification: str | None = None, message: dict | None = None
    ) -> Any:
        body: dict[str, Any] = {}
        if notification:
            body["notification"] = notification
        if message:
            body["message"] = message
        return await self._request(
            "POST", "/answers", params={"callback_id": callback_id}, json=body
        )

    # ── Файлы: три шага ───────────────────────────────────────────

    async def upload_file(self, path: Path, upload_type: str = "file") -> dict:
        """Возвращает payload для attachments — обычно {"token": "..."}."""
        meta = await self._request("POST", "/uploads", params={"type": upload_type})
        upload_url = meta.get("url") if isinstance(meta, dict) else None
        if not upload_url:
            raise MaxApiError(500, f"в ответе /uploads нет url: {meta}")

        await self._limiter.wait()
        client = await self._http()
        with path.open("rb") as fh:
            files = {"data": (path.name, fh, "application/octet-stream")}
            # на сам upload-хост токен слать не нужно
            resp = await client.post(upload_url, files=files, headers={"Authorization": ""})
        if resp.status_code >= 400:
            raise MaxApiError(resp.status_code, resp.text)

        try:
            data = resp.json()
        except ValueError:
            data = {}

        # Форма ответа может отличаться — нормализуем к payload для attachments
        if isinstance(data, dict):
            if "token" in data:
                return {"token": data["token"]}
            for key in ("photos", "file", "video", "audio"):
                if key in data and isinstance(data[key], dict):
                    inner = data[key]
                    if "token" in inner:
                        return {"token": inner["token"]}
            if "url" in data:
                return {"url": data["url"]}
        raise MaxApiError(500, f"не удалось разобрать ответ загрузки: {data}")

    async def send_document(
        self,
        user_id: int,
        path: Path,
        text: str = "",
        retries: int = 5,
    ) -> dict:
        """Загрузить и отправить файл.

        Третий шаг регулярно падает сразу после второго — медиа ещё обрабатывается.
        Поэтому ретраим именно отправку, повторно не загружая файл.
        """
        payload = await self.upload_file(path, "file")
        attachment = {"type": "file", "payload": payload}

        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                return await self.send_message(user_id, text, [attachment])
            except MaxApiError as exc:
                last_error = exc
                # 400/404 сразу после загрузки = ещё не обработано
                if exc.status in (400, 404, 409, 500, 502, 503):
                    delay = min(2 ** attempt, 15)
                    log.info(
                        "Вложение ещё не готово (попытка %s/%s), ждём %ss",
                        attempt + 1,
                        retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        raise MaxApiError(500, f"не удалось отправить документ: {last_error}")

    # ── Вебхуки ───────────────────────────────────────────────────

    async def list_subscriptions(self) -> Any:
        return await self._request("GET", "/subscriptions")

    async def subscribe(self, url: str, secret: str | None = None) -> Any:
        body: dict[str, Any] = {"url": url}
        if secret:
            body["secret"] = secret
        return await self._request("POST", "/subscriptions", json=body)

    async def unsubscribe(self, url: str) -> Any:
        return await self._request("DELETE", "/subscriptions", params={"url": url})

    async def get_updates(self, marker: int | None = None, timeout: int = 30) -> dict:
        params: dict[str, Any] = {"timeout": timeout, "limit": 100}
        if marker is not None:
            params["marker"] = marker
        return await self._request("GET", "/updates", params=params)


max_client = MaxClient()


# Кнопка open_app работает только после того, как организаторы привяжут
# мини-приложение к боту. До этого MAX отвечает «Field 'webApp' cannot be null»
# и сообщение не доходит вообще. Флаг выставляется по первой такой ошибке,
# дальше вместо open_app отправляется обычная ссылка на то же приложение —
# из чата оно открывается в браузере.
_open_app_supported = True


def open_app_supported() -> bool:
    return _open_app_supported


def _is_webapp_error(exc: MaxApiError) -> bool:
    return "webApp" in exc.body or "web_app" in exc.body


async def send_with_app_button(user_id: int, text: str, label: str | None = None) -> None:
    """Отправить сообщение с кнопкой входа в приложение, деградируя по обстоятельствам.

    Порядок попыток: open_app → обычная ссылка → просто текст.
    Сообщение должно дойти в любом случае — это важнее кнопки.
    """
    global _open_app_supported

    if not label:
        await max_client.send_message(user_id, text)
        return

    if _open_app_supported:
        try:
            await max_client.send_message(user_id, text, [keyboard([[btn_open_app(label)]])])
            return
        except MaxApiError as exc:
            if not _is_webapp_error(exc):
                raise
            _open_app_supported = False
            log.warning(
                "Мини-приложение ещё не привязано к боту организаторами — "
                "кнопка open_app отключена, дальше отправляем ссылку"
            )

    public_url = settings.MINIAPP_PUBLIC_URL.strip().rstrip("/")
    if public_url.startswith("https://"):
        try:
            await max_client.send_message(
                user_id, text, [keyboard([[btn_link(label, public_url)]])]
            )
            return
        except MaxApiError as exc:
            log.warning("Кнопка-ссылка тоже не прошла (%s), отправляем текстом", exc.status)

    await max_client.send_message(user_id, text)


# ── Сборка клавиатур ──────────────────────────────────────────────


def keyboard(rows: list[list[dict]]) -> dict:
    """Клавиатура в MAX — вложение, а не reply_markup."""
    return {"type": "inline_keyboard", "payload": {"buttons": rows}}


def btn_open_app(text: str) -> dict:
    return {"type": "open_app", "text": text}


def btn_link(text: str, url: str) -> dict:
    return {"type": "link", "text": text, "url": url}


def btn_callback(text: str, payload: str) -> dict:
    return {"type": "callback", "text": text, "payload": payload}
