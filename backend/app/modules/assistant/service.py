"""Оркестрация ассистента: принудительный RAG + цикл вызова инструментов."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AiMessage, Conversation, Student, utcnow
from app.modules.assistant import rag
from app.modules.assistant import tools as tools_mod
from app.modules.assistant.llm import get_llm
from app.modules.assistant.prompts import NOT_FOUND_PHRASE, build_system_prompt
from app.modules.assistant.tools import TOOL_SCHEMAS, ToolContext, dispatch

log = logging.getLogger("assistant.service")

HISTORY_LIMIT = 8
MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


@dataclass
class AssistantAnswer:
    text: str
    sources: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    tool_trace: list[str] = field(default_factory=list)


def _today_ru() -> str:
    now = datetime.now()
    return f"{now.day} {MONTHS[now.month - 1]} {now.year}"


# Модель иногда пишет вызов инструмента ПРОСТЫМ ТЕКСТОМ вместо структурного
# tool_calls: строка вида "[escalate_to_human]" и следом JSON с аргументами.
# Такой текст нельзя показывать пользователю — вычищаем.
_PSEUDO_TOOL = re.compile(
    r"^\s*\[?(get_my_requests|list_request_templates|start_request|list_events|"
    r"list_opportunities|get_my_matches|escalate_to_human|search_regulations)\]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BARE_JSON_LINE = re.compile(r"^\s*[\{\[].*[\}\]]\s*$", re.MULTILINE)

_REFUSAL_MARKERS = (
    "не знаю",
    "уточните в деканате",
    "не могу понять",
    "уточните ваш запрос",
    "недостаточно информации",
)


def _sanitize(text: str) -> str:
    """Убирает псевдо-вызовы инструментов и голые JSON-строки из ответа."""
    cleaned = _PSEUDO_TOOL.sub("", text)
    cleaned = _BARE_JSON_LINE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _looks_like_refusal(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _REFUSAL_MARKERS)


def _relevant_sources(answer: str, sources: list[dict]) -> list[dict]:
    """Оставляет только те источники, которые реально отразились в ответе.

    Без этой фильтрации под ответом про хакатоны появлялись ссылки на
    «Материальную помощь» — формально найденные RAG-ом, но к делу не идущие.
    """
    if not sources or _looks_like_refusal(answer):
        return []

    answer_words = {w for w in re.findall(r"[а-яёa-z]{6,}", answer.lower())}
    if not answer_words:
        return []

    kept: list[dict] = []
    for src in sources:
        snippet_words = {w for w in re.findall(r"[а-яёa-z]{6,}", src.get("snippet", "").lower())}
        if len(answer_words & snippet_words) >= 3:
            kept.append(src)
    return kept[:3]


async def _get_or_create_conversation(session: AsyncSession, app_user_id: int) -> Conversation:
    res = await session.execute(
        select(Conversation)
        .where(Conversation.app_user_id == app_user_id)
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    conv = res.scalar_one_or_none()
    if conv is None:
        conv = Conversation(app_user_id=app_user_id)
        session.add(conv)
        await session.flush()
    return conv


async def _load_history(session: AsyncSession, conversation_id: int) -> list[dict]:
    res = await session.execute(
        select(AiMessage)
        .where(AiMessage.conversation_id == conversation_id)
        .order_by(AiMessage.id.desc())
        .limit(HISTORY_LIMIT)
    )
    rows = list(res.scalars())[::-1]
    return [{"role": m.role, "content": m.content} for m in rows if m.content]


async def ask(
    session: AsyncSession,
    *,
    student: Student,
    app_user_id: int,
    question: str,
) -> AssistantAnswer:
    """Основной вход. RAG выполняется всегда, до обращения к модели."""
    conv = await _get_or_create_conversation(session, app_user_id)
    history = await _load_history(session, conv.id)

    session.add(AiMessage(conversation_id=conv.id, role="user", content=question))
    conv.last_message_at = utcnow()
    await session.flush()

    if not settings.llm_enabled:
        answer = AssistantAnswer(
            text="Ассистент сейчас недоступен — не настроен доступ к языковой модели. "
                 "Остальные разделы приложения работают."
        )
        session.add(AiMessage(conversation_id=conv.id, role="assistant", content=answer.text))
        return answer

    # ── Шаг 1: принудительный поиск по базе знаний (решение 019) ──
    fragments = await rag.search(session, question)
    fragments_text = rag.format_fragments(fragments)
    sources = [
        {"title": f.title, "url": f.source_url, "snippet": f.text[:220]} for f in fragments
    ]

    ctx = ToolContext(session=session, student=student, app_user_id=app_user_id)

    # ── Шаг 2: предзапрос очевидно нужных данных (решение 030) ──
    # Модель не всегда вызывает инструмент и тогда может выдумать список
    # мероприятий. Подтягиваем данные сами, чтобы выдумывать было нечего.
    data_blocks = await tools_mod.prefetch(ctx, question)

    system_prompt = build_system_prompt(student, fragments_text, _today_ru(), data_blocks)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})
    llm = get_llm()
    trace: list[str] = list(ctx.called)
    # Предзапрошенное — такой же источник фактов, как и результат вызова:
    # попадёт в финальный проход, если модель проигнорирует данные.
    tool_outputs: list[tuple[str, str]] = [(title, content) for title, content in data_blocks]
    final_text = ""
    llm_failed = False

    # ── Шаг 2: цикл инструментов, максимум N итераций (решение 020) ──
    for iteration in range(settings.ASSISTANT_MAX_TOOL_ITERATIONS):
        try:
            result = await llm.chat(messages, TOOL_SCHEMAS)
        except Exception:
            log.exception("Ошибка обращения к модели")
            final_text = (
                "Не получилось связаться с языковой моделью. Попробуй ещё раз через минуту."
            )
            llm_failed = True
            break

        if not result.wants_tools:
            final_text = result.text
            break

        messages.append(
            {
                "role": "assistant",
                "content": result.text or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": _dump_args(tc.arguments)},
                    }
                    for tc in result.tool_calls
                ],
            }
        )

        for tc in result.tool_calls:
            trace.append(tc.name)
            log.info("Инструмент %s(%s) итерация %s", tc.name, tc.arguments, iteration + 1)
            output = await dispatch(ctx, tc.name, tc.arguments)
            tool_outputs.append((tc.name, output))
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
    else:
        final_text = await _finalize(llm, messages, tool_outputs)

    final_text = _sanitize(final_text)

    # Инструменты отработали, данные есть — а модель всё равно отвечает «не знаю».
    # Это её известная слабость: она теряет результат вызова. Переспрашиваем один
    # раз без инструментов, подставив собранные данные прямым текстом.
    if not llm_failed and tool_outputs and (not final_text or _looks_like_refusal(final_text)):
        log.info("Модель проигнорировала результат инструментов — финальный проход без них")
        retry_text = await _finalize(llm, messages, tool_outputs)
        retry_text = _sanitize(retry_text)
        if retry_text and not _looks_like_refusal(retry_text):
            final_text = retry_text

    if not final_text:
        final_text = NOT_FOUND_PHRASE

    answer = AssistantAnswer(
        text=final_text.strip(),
        sources=_relevant_sources(final_text, sources),
        actions=ctx.ui_actions,
        tool_trace=trace,
    )

    session.add(
        AiMessage(
            conversation_id=conv.id,
            role="assistant",
            content=answer.text,
            sources_json=answer.sources,
            tool_calls_json=trace,
        )
    )
    conv.last_message_at = utcnow()
    await session.flush()
    return answer


def _dump_args(args: dict) -> str:
    return json.dumps(args, ensure_ascii=False)


async def _finalize(llm, messages: list[dict], tool_outputs: list[tuple[str, str]]) -> str:
    """Просит модель сформулировать ответ по уже собранным данным, без инструментов.

    Данные дублируем простым текстом: модель заметно надёжнее читает их из
    обычного сообщения, чем из истории вызовов инструментов.
    """
    collected = "\n\n".join(f"Данные из «{name}»:\n{output}" for name, output in tool_outputs)
    prompt = (
        "Ниже данные, которые уже получены по запросу студента. "
        "Ответь на его вопрос, опираясь только на них. Инструменты не вызывай.\n"
        "Если в данных есть записи — перечисли конкретику: номера, статусы, сроки, названия.\n"
        "Если список пуст — так прямо и скажи (например: «у тебя пока нет заявок» "
        "или «ближайших событий нет»). Фразу «не знаю» в этом случае не используй.\n\n"
        + collected
    )
    try:
        result = await llm.chat(messages + [{"role": "user", "content": prompt}], tools=None)
        return result.text or ""
    except Exception:
        log.exception("Не удалось получить финальный ответ")
        return "Данные собрал, но не смог сформулировать ответ. Попробуй переспросить."
