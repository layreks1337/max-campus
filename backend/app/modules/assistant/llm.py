"""Провайдер LLM за абстракцией.

Сейчас — Yandex Foundation Models через OpenAI-совместимый эндпоинт
(решение 017: стандартный формат tools, готовый SDK, меньше своего кода).

Проверено вживую 24.09.2026, подробности и грабли — docs/05-llm-notes.md:
  • function calling работает, формат стандартный
  • стриминг SSE работает
  • prompt caching отсутствует -> промпты держим компактными
  • модель не доводит цепочку инструментов до конца -> RAG принудительный (решение 019)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import settings

log = logging.getLogger("assistant.llm")

# Квота Yandex на эмбеддинги — 10 запросов в секунду. Держим запас,
# иначе индексация базы знаний валится на 429 и часть чанков остаётся без вектора.
EMBED_MIN_INTERVAL = 0.15
EMBED_MAX_RETRIES = 5


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(Protocol):
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        cheap: bool = False,
        temperature: float = 0.2,
    ) -> ChatResult: ...

    async def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]: ...


class YandexProvider:
    """Yandex Foundation Models. Чат — через OpenAI-совместимый путь, эмбеддинги — нативно."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._embed_lock = asyncio.Lock()
        self._last_embed_at = 0.0

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Api-Key {settings.YC_API_KEY}",
            "OpenAI-Project": settings.YC_FOLDER_ID,
            "Content-Type": "application/json; charset=utf-8",
        }

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        cheap: bool = False,
        temperature: float = 0.2,
    ) -> ChatResult:
        if not settings.llm_enabled:
            raise RuntimeError("LLM не настроен: нужны YC_API_KEY и YC_FOLDER_ID")

        body: dict[str, Any] = {
            "model": settings.model_uri_cheap if cheap else settings.model_uri_main,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        client = await self._http()
        resp = await client.post(
            f"{settings.YC_OPENAI_BASE}/chat/completions",
            headers=self._headers,
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
        if resp.status_code >= 400:
            log.error("LLM %s: %s", resp.status_code, resp.text[:500])
            raise RuntimeError(f"LLM вернул {resp.status_code}")

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}

        calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                # всегда json.loads — экранирование у разных моделей отличается
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))

        return ChatResult(
            text=(msg.get("content") or "").strip(),
            tool_calls=calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage=data.get("usage") or {},
        )

    async def _throttle_embed(self) -> None:
        async with self._embed_lock:
            delta = time.monotonic() - self._last_embed_at
            if delta < EMBED_MIN_INTERVAL:
                await asyncio.sleep(EMBED_MIN_INTERVAL - delta)
            self._last_embed_at = time.monotonic()

    async def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        """Две РАЗНЫЕ модели: doc для чанков при индексации, query для поиска."""
        if not settings.llm_enabled:
            raise RuntimeError("LLM не настроен")

        model = settings.EMBEDDING_MODEL_QUERY if is_query else settings.EMBEDDING_MODEL_DOC
        model_uri = f"emb://{settings.YC_FOLDER_ID}/{model}"
        client = await self._http()

        vectors: list[list[float]] = []
        for text in texts:
            payload = {"modelUri": model_uri, "text": text[:4000]}
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            for attempt in range(EMBED_MAX_RETRIES):
                await self._throttle_embed()
                resp = await client.post(
                    settings.EMBEDDING_URL, headers=self._headers, content=body
                )
                if resp.status_code == 429:
                    delay = min(1.5 * (attempt + 1), 6.0)
                    log.info("Квота эмбеддингов исчерпана, ждём %.1fs", delay)
                    await asyncio.sleep(delay)
                    continue
                if resp.status_code >= 400:
                    log.error("Эмбеддинг %s: %s", resp.status_code, resp.text[:300])
                    raise RuntimeError(f"Эмбеддинг вернул {resp.status_code}")
                vectors.append(resp.json().get("embedding", []))
                break
            else:
                raise RuntimeError("Эмбеддинг: квота не восстановилась за отведённые попытки")
        return vectors


_provider: YandexProvider | None = None


def get_llm() -> YandexProvider:
    global _provider
    if _provider is None:
        _provider = YandexProvider()
    return _provider


async def close_llm() -> None:
    global _provider
    if _provider is not None:
        await _provider.aclose()
        _provider = None
