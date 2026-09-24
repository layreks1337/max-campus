"""Чат с ассистентом внутри мини-приложения."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sqlalchemy import select

from app.api.schemas import (
    AskIn,
    AskOut,
    ChatHistoryOut,
    ChatMessageOut,
    SourceOut,
)
from app.core.config import settings
from app.core.deps import BoundUserDep, SessionDep
from app.db.models import AiMessage, Conversation
from app.modules.assistant import service as assistant
from app.modules.assistant.prompts import SUGGESTIONS

log = logging.getLogger("api.assistant")
router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/ask", response_model=AskOut, summary="Задать вопрос ассистенту")
async def ask(body: AskIn, current: BoundUserDep, session: SessionDep) -> AskOut:
    answer = await assistant.ask(
        session,
        student=current.student,
        app_user_id=current.app_user.id,
        question=body.question.strip(),
    )
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
    res = await session.execute(
        select(Conversation).where(Conversation.app_user_id == current.app_user.id)
    )
    for conv in res.scalars():
        msgs = await session.execute(
            select(AiMessage).where(AiMessage.conversation_id == conv.id)
        )
        for m in msgs.scalars():
            await session.delete(m)
        await session.delete(conv)
    return {"ok": True}


@router.get("/status", summary="Доступен ли ассистент")
async def assistant_status() -> dict:
    return {
        "enabled": settings.llm_enabled,
        "model": settings.LLM_MODEL_MAIN if settings.llm_enabled else None,
        "suggestions": SUGGESTIONS,
    }
