"""Чат с ассистентом внутри мини-приложения."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request as HttpRequest, status
from sqlalchemy import delete, select

from app.api.schemas import (
    AskIn,
    AskOut,
    ChatHistoryOut,
    ChatMessageOut,
    SourceOut,
)
from app.core.config import is_test_user_id, settings
from app.core.deps import BoundUserDep, SessionDep
from app.core.limits import SlidingWindow, client_ip
from app.db.models import AiMessage, Conversation
from app.modules.assistant import service as assistant
from app.modules.assistant.prompts import SUGGESTIONS

log = logging.getLogger("api.assistant")
router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/ask", response_model=AskOut, summary="Задать вопрос ассистенту")
async def ask(
    body: AskIn, request: HttpRequest, current: BoundUserDep, session: SessionDep
) -> AskOut:
    # Тестовый вход — ещё и лимит с адреса: сменой id лимит на пользователя не обойти
    test_login = is_test_user_id(current.app_user.max_user_id)
    try:
        answer = await assistant.ask(
            session,
            student=current.student,
            app_user_id=current.app_user.id,
            question=body.question.strip(),
            rate_ip=client_ip(request) if test_login else None,
        )
    except assistant.RateLimited as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMITED",
                "message": assistant.rate_limit_message(exc.retry_after),
                "details": {"retry_after": exc.retry_after},
            },
        ) from None
    return AskOut(
        answer=answer.text,
        sources=[SourceOut(**s) for s in answer.sources],
        actions=answer.actions,
        tools_used=answer.tool_trace,
    )


@router.get("/history", response_model=ChatHistoryOut, summary="История диалога")
async def history(current: BoundUserDep, session: SessionDep) -> ChatHistoryOut:
    res = await session.execute(
        select(Conversation)
        .where(Conversation.app_user_id == current.app_user.id)
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    conv = res.scalar_one_or_none()
    if conv is None:
        return ChatHistoryOut(messages=[], suggestions=SUGGESTIONS)

    res = await session.execute(
        select(AiMessage)
        .where(AiMessage.conversation_id == conv.id)
        .order_by(AiMessage.id.desc())
        .limit(50)
    )
    rows = list(res.scalars())[::-1]
    return ChatHistoryOut(
        messages=[
            ChatMessageOut(
                role=m.role,
                content=m.content,
                sources=[SourceOut(**s) for s in (m.sources_json or [])],
                created_at=m.created_at,
            )
            for m in rows
        ],
        suggestions=SUGGESTIONS if not rows else [],
    )


@router.delete("/history", summary="Очистить диалог")
async def clear_history(current: BoundUserDep, session: SessionDep) -> dict:
    # Строки диалогов блокируются до удаления сообщений. Ответ ассистента,
    # который как раз сохраняется, либо успевает раньше и удаляется вместе со
    # всеми, либо ждёт очистки и не сохраняется (assistant.ask) — без 500 ни
    # у очистки, ни у вопроса.
    ids = list(
        (
            await session.execute(
                select(Conversation.id)
                .where(Conversation.app_user_id == current.app_user.id)
                .with_for_update()
            )
        ).scalars()
    )
    if ids:
        await session.execute(delete(AiMessage).where(AiMessage.conversation_id.in_(ids)))
        await session.execute(delete(Conversation).where(Conversation.id.in_(ids)))
    return {"ok": True}


@router.get("/status", summary="Доступен ли ассистент")
async def assistant_status() -> dict:
    return {
        "enabled": settings.llm_enabled,
        "model": settings.LLM_MODEL_MAIN if settings.llm_enabled else None,
        "suggestions": SUGGESTIONS,
    }


# ── Голосовой вопрос ──────────────────────────────────────────────

MAX_AUDIO_BYTES = 16_000 * 2 * 30  # 30 секунд моно PCM 16 кГц

# Распознавание — платный вызов SpeechKit: те же лимиты, что у вопросов
_voice_by_user = SlidingWindow(settings.ASSISTANT_RATE_LIMIT, settings.ASSISTANT_RATE_WINDOW_SECONDS)
_voice_by_ip = SlidingWindow(
    settings.ASSISTANT_RATE_LIMIT_PER_IP, settings.ASSISTANT_RATE_WINDOW_SECONDS
)


@router.post("/transcribe", summary="Распознать голосовой вопрос")
async def transcribe(request: HttpRequest, current: BoundUserDep) -> dict:
    """Приложение пишет звук в PCM 16 кГц прямо в браузере и шлёт сюда сырые
    байты — SpeechKit принимает их без перекодирования, а формат WebM,
    который отдаёт MediaRecorder, он не понимает."""
    if not settings.llm_enabled:
        raise HTTPException(503, detail={"code": "UNAVAILABLE", "message": "Распознавание речи не настроено"})
    ip = client_ip(request) if is_test_user_id(current.app_user.max_user_id) else None
    if (ip is not None and not _voice_by_ip.allowed(ip)) or not _voice_by_user.take(current.app_user.id):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED", "message": "Слишком много голосовых вопросов — напишите текстом"},
        )
    if ip is not None:
        _voice_by_ip.hit(ip)
    audio = await request.body()
    if len(audio) < 3200:
        raise HTTPException(422, detail={"code": "TOO_SHORT", "message": "Запись слишком короткая"})
    audio = audio[:MAX_AUDIO_BYTES]
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize",
                params={
                    "folderId": settings.YC_FOLDER_ID,
                    "lang": "ru-RU",
                    "format": "lpcm",
                    "sampleRateHertz": 16000,
                },
                headers={"Authorization": f"Api-Key {settings.YC_API_KEY}"},
                content=audio,
            )
        resp.raise_for_status()
        text = (resp.json().get("result") or "").strip()
    except httpx.HTTPError as exc:
        log.warning("SpeechKit недоступен: %s", exc)
        raise HTTPException(502, detail={"code": "STT_FAILED", "message": "Не удалось распознать речь"})
    return {"text": text}
