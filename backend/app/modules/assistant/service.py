"""Оркестрация ассистента: принудительный RAG + цикл вызова инструментов.

Ответ ограничен по времени и по частоте (решения 060, 061): не дольше
ASSISTANT_TIMEOUT_SECONDS, не больше ASSISTANT_RATE_LIMIT вопросов за окно.
Если модель не уложилась или упала, человек получает не ошибку, а выдержки
из найденных регламентов с честной пометкой, что модель не ответила.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.limits import SlidingWindow
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

# Запасной ответ: сколько выдержек показать и какой длины
FALLBACK_NOTE = "Модель не ответила — вот что сказано в регламенте."
FALLBACK_FRAGMENTS = 2
FALLBACK_EXCERPT_CHARS = 420
# Что добирается для запасного ответа после таймаута (запись обращения, поиск,
# данные студента) — только база, но и её не ждём вечно
FALLBACK_SEARCH_SECONDS = 5.0


@dataclass
class AssistantAnswer:
    text: str
    sources: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    tool_trace: list[str] = field(default_factory=list)


@dataclass
class _Progress:
    """Что успело собраться до таймаута — из этого строится запасной ответ."""

    fragments: list[rag.Fragment] | None = None
    prefetched: bool = False
    actions: list[dict] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    # Обращения в деканат (номера) и задачи их записи — см. tools._escalate_to_human
    escalations: list[str] = field(default_factory=list)
    writes: list[asyncio.Task] = field(default_factory=list)


# ── Лимит вопросов ────────────────────────────────────────────────


class RateLimited(Exception):
    """Пользователь исчерпал лимит вопросов; retry_after — секунд до следующего."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Лимит вопросов, повтор через {retry_after} с")
        self.retry_after = retry_after


# Моменты вопросов за последнее окно — по пользователю, на весь процесс.
# Как и у лимита кодов привязки: память процесса, рестарт обнуляет — для
# защиты баланса от скрипта этого достаточно.
_asked: dict[int, deque[float]] = defaultdict(deque)
# Вопросы тестовых id с одного адреса (решение 067): их id не стоят ничего
_asked_by_ip = SlidingWindow(
    settings.ASSISTANT_RATE_LIMIT_PER_IP, settings.ASSISTANT_RATE_WINDOW_SECONDS
)


def check_rate(app_user_id: int, ip: str | None = None) -> None:
    """Учитывает вопрос или поднимает RateLimited, если лимит исчерпан.

    ip — адрес клиента, если вход тестовый: тогда действует и лимит с адреса.
    """
    now = time.monotonic()
    window = settings.ASSISTANT_RATE_WINDOW_SECONDS
    if ip is not None and not _asked_by_ip.allowed(ip):
        raise RateLimited(window)

    if len(_asked) > 2048:
        # Разовая уборка: иначе словарь копит всех, кто когда-то спрашивал
        for uid in [u for u, q in _asked.items() if not q or now - q[-1] >= window]:
            del _asked[uid]

    stamps = _asked[app_user_id]
    while stamps and now - stamps[0] >= window:
        stamps.popleft()
    if len(stamps) >= settings.ASSISTANT_RATE_LIMIT:
        raise RateLimited(max(1, math.ceil(stamps[0] + window - now)))
    stamps.append(now)
    if ip is not None:
        _asked_by_ip.hit(ip)


def _minutes(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} минуту"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} минуты"
    return f"{n} минут"


def rate_limit_message(retry_after: int) -> str:
    wait = _minutes(max(1, math.ceil(retry_after / 60)))
    window = _minutes(max(1, settings.ASSISTANT_RATE_WINDOW_SECONDS // 60))
    return (
        f"Давай сделаем паузу: снова спросить можно через {wait}. "
        f"Лимит — {settings.ASSISTANT_RATE_LIMIT} вопросов за {window}, "
        "чтобы ассистента хватило всем. Заявки, расписание и афиша работают как обычно."
    )


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
    titles: set[str] = set()
    for src in sources:
        # Несколько фрагментов одного документа — один источник, а не два
        # одинаковых заголовка подряд
        if src.get("title") in titles:
            continue
        snippet_words = {w for w in re.findall(r"[а-яёa-z]{6,}", src.get("snippet", "").lower())}
        if len(answer_words & snippet_words) >= 3:
            kept.append(src)
            titles.add(src.get("title"))
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


# Ответы, которые готовятся прямо сейчас: (пользователь, вопрос) → будущий ответ.
# «Повторить» в чате бросает ожидание и шлёт тот же вопрос заново, а первый
# запрос на сервере при этом продолжает работать (отключение клиента его не
# прерывает). Повтор присоединяется к нему (решение 061): без второго вызова
# модели, без дубля вопроса в истории и без траты лимита, а запасной ответ
# приходит в свой срок — через 25 секунд от первого запроса, а не от повтора.
_pending: dict[tuple[int, str], asyncio.Future] = {}


async def ask(
    session: AsyncSession,
    *,
    student: Student,
    app_user_id: int,
    question: str,
    rate_ip: str | None = None,
) -> AssistantAnswer:
    """Основной вход. RAG выполняется всегда, до обращения к модели.

    Поднимает RateLimited, если пользователь исчерпал лимит вопросов, — вопрос
    тогда не сохраняется и в модель не уходит. Тот же вопрос, пока на него
    готовится ответ, не задаётся заново, а получает этот ответ (_pending).
    """
    key = (app_user_id, question)
    running = _pending.get(key)
    if running is not None:
        log.info("Тот же вопрос ещё в работе — ждём его ответ, а не спрашиваем заново")
        joined = await asyncio.shield(running)
        if joined is not None:
            return joined
        # Первый запрос упал — отвечаем сами, как на новый вопрос

    done: asyncio.Future = asyncio.get_running_loop().create_future()
    _pending[key] = done
    answer: AssistantAnswer | None = None
    try:
        answer = await _ask(
            session, student=student, app_user_id=app_user_id, question=question,
            rate_ip=rate_ip,
        )
        return answer
    finally:
        # None — ответа нет (ошибка, лимит): присоединившийся ответит сам
        done.set_result(answer)
        if _pending.get(key) is done:
            del _pending[key]


async def _ask(
    session: AsyncSession,
    *,
    student: Student,
    app_user_id: int,
    question: str,
    rate_ip: str | None = None,
) -> AssistantAnswer:
    check_rate(app_user_id, rate_ip)

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

    # Вопрос фиксируем до обращения к модели: по таймауту транзакция
    # откатывается (ниже), и вопрос не должен пропасть из истории вместе с ней.
    conv_id = conv.id
    await session.commit()

    progress = _Progress()
    try:
        answer = await asyncio.wait_for(
            _answer(
                session,
                student=student,
                app_user_id=app_user_id,
                question=question,
                history=history,
                progress=progress,
            ),
            timeout=settings.ASSISTANT_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        log.warning(
            "Ответ не уложился в %.0f с — отдаём выдержки из регламента",
            settings.ASSISTANT_TIMEOUT_SECONDS,
        )
        # Отмена могла прервать запрос к базе посреди выполнения, и соединение
        # осталось в неизвестном состоянии — откатываем. Терять при этом нечего:
        # вопрос уже закоммичен, инструменты данных только читают, а единственный
        # пишущий — обращение в деканат — пишется в своей сессии и коммитится
        # сразу (решение 061).
        await session.rollback()
        await _fallback_collect(session, student, app_user_id, question, progress)
        answer = _fallback(progress, question)

    # Диалог могли очистить, пока готовился ответ (кнопка в шапке чата): тогда
    # сохранять ответ некуда — вставка упадёт на внешнем ключе. Ответ всё равно
    # отдаём, а сбой ограничиваем точкой сохранения, чтобы не уронить запрос.
    try:
        async with session.begin_nested():
            session.add(
                AiMessage(
                    conversation_id=conv_id,
                    role="assistant",
                    content=answer.text,
                    sources_json=answer.sources,
                    tool_calls_json=answer.tool_trace,
                )
            )
            # Через UPDATE, а не атрибутом: после отката объект просрочен, и чтение
            # атрибута полезло бы в базу вне async-контекста (MissingGreenlet)
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conv_id)
                .values(last_message_at=utcnow())
            )
            await session.flush()
    except IntegrityError:
        log.info("Диалог очищен, пока готовился ответ, — ответ не сохраняем")
    return answer


async def _answer(
    session: AsyncSession,
    *,
    student: Student,
    app_user_id: int,
    question: str,
    history: list[dict],
    progress: _Progress,
) -> AssistantAnswer:
    """Поиск, предзапрос, цикл инструментов и проверка ответа — всё, что под таймаутом."""
    # ── Шаг 1: принудительный поиск по базе знаний (решение 019) ──
    fragments = await rag.search(session, question)
    progress.fragments = fragments
    fragments_text = rag.format_fragments(fragments)
    sources = [
        {"title": f.title, "url": f.source_url, "snippet": f.text[:220]} for f in fragments
    ]

    # Кнопки и обращения копятся прямо в progress: если модель не успеет, они всё
    # равно попадут в запасной ответ — например, «Открыть заявку» из предзапроса.
    ctx = _tool_context(session, student, app_user_id, progress)

    # ── Шаг 2: предзапрос очевидно нужных данных (решение 030) ──
    # Модель не всегда вызывает инструмент и тогда может выдумать список
    # мероприятий. Подтягиваем данные сами, чтобы выдумывать было нечего.
    data_blocks = await tools_mod.prefetch(ctx, question)
    progress.prefetched = True

    system_prompt = build_system_prompt(student, fragments_text, _today_ru(), data_blocks)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})
    llm = get_llm()
    trace = progress.trace
    trace.extend(ctx.called)
    # Предзапрошенное — такой же источник фактов, как и результат вызова:
    # попадёт в финальный проход, если модель проигнорирует данные.
    tool_outputs: list[tuple[str, str]] = [(title, content) for title, content in data_blocks]
    final_text: str | None = ""

    # ── Шаг 2: цикл инструментов, максимум N итераций (решение 020) ──
    for iteration in range(settings.ASSISTANT_MAX_TOOL_ITERATIONS):
        try:
            result = await llm.chat(messages, TOOL_SCHEMAS)
        except Exception:
            log.exception("Ошибка обращения к модели — отдаём выдержки из регламента")
            return _fallback(progress, question)

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
        if final_text is None:
            return _fallback(progress, question)

    final_text = _sanitize(final_text)

    # Инструменты отработали, данные есть — а модель всё равно отвечает «не знаю».
    # Это её известная слабость: она теряет результат вызова. Переспрашиваем один
    # раз без инструментов, подставив собранные данные прямым текстом.
    if tool_outputs and (not final_text or _looks_like_refusal(final_text)):
        log.info("Модель проигнорировала результат инструментов — финальный проход без них")
        retry_text = await _finalize(llm, messages, tool_outputs)
        if retry_text is None:
            return _fallback(progress, question)
        retry_text = _sanitize(retry_text)
        if retry_text and not _looks_like_refusal(retry_text):
            final_text = retry_text

    if not final_text:
        final_text = NOT_FOUND_PHRASE

    return AssistantAnswer(
        text=final_text.strip(),
        sources=_relevant_sources(final_text, sources),
        actions=ctx.ui_actions,
        tool_trace=trace,
    )


# ── Запасной ответ: модель не ответила ────────────────────────────


def _tool_context(
    session: AsyncSession, student: Student, app_user_id: int, progress: _Progress
) -> ToolContext:
    """Контекст инструментов, который складывает кнопки и обращения в progress."""
    return ToolContext(
        session=session,
        student=student,
        app_user_id=app_user_id,
        ui_actions=progress.actions,
        escalations=progress.escalations,
        writes=progress.writes,
    )


async def _fallback_collect(
    session: AsyncSession,
    student: Student,
    app_user_id: int,
    question: str,
    progress: _Progress,
) -> None:
    """Добирает после таймаута то, что нужно запасному ответу. Не дольше
    FALLBACK_SEARCH_SECONDS на всё:

    - запись обращения в деканат, которую таймаут не прервал (shield), — чтобы
      назвать номер, а не промолчать о нём;
    - поиск, если таймаут наступил раньше него. Обычно так бывает, когда Yandex
      не отдаёт эмбеддинг вопроса, поэтому здесь только полнотекст по своей базе;
    - предзапрос данных студента, если до него не дошло, — кнопки «Заявка №…»
      к вопросу про свою заявку.
    """

    async def collect() -> None:
        if progress.writes:
            await asyncio.wait(progress.writes)
        if progress.fragments is None:
            progress.fragments = await rag.search(session, question, vector=False)
        if not progress.prefetched:
            # После отката студент просрочен — перечитываем, иначе инструменты
            # полезли бы за его полями в базу вне async-контекста
            await session.refresh(student)
            ctx = _tool_context(session, student, app_user_id, progress)
            await tools_mod.prefetch(ctx, question)
            progress.prefetched = True
            progress.trace.extend(ctx.called)

    try:
        await asyncio.wait_for(collect(), timeout=FALLBACK_SEARCH_SECONDS)
    except Exception:
        log.exception("Запасной ответ собран не полностью")
        # Отмена снова могла оборвать запрос к базе — ответ сохраняется следом
        await session.rollback()
    if progress.fragments is None:
        progress.fragments = []


def _excerpt(text: str, limit: int = FALLBACK_EXCERPT_CHARS) -> str:
    """Читаемая выдержка из фрагмента: целые предложения, не длиннее limit.

    Фрагмент базы знаний начинается с хвоста предыдущего (перекрытие чанков,
    rag.CHUNK_OVERLAP) — часто с середины слова. Такое начало отбрасываем.
    """
    flat = " ".join(text.split())
    sentences = [s for s in re.split(r"(?<=[.!?…])\s+", flat) if s]
    if len(sentences) > 1 and not (sentences[0][0].isupper() or sentences[0][0] in "«\"0123456789•—-"):
        sentences = sentences[1:]

    out = ""
    for sent in sentences:
        if out and len(out) + 1 + len(sent) > limit:
            return out + " …"
        out = f"{out} {sent}".strip()
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0] + " …"
    return out


def _stem(word: str) -> str:
    # Грубая основа: «справка/справки/справку» → «справ», «клубы/клуб» → «клуб»
    return word[: max(4, min(5, len(word) - 1))]


def _stems(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[а-яёa-z]{4,}", text.lower())}


# Слова, которые есть почти в любом вопросе или любом регламенте, —
# по ним выдержку к вопросу не привязать
_STOP_STEMS = _stems(
    "сколько какие какой какая какое каких когда нужно нужна нужен нужны можно "
    "почему зачем который которые чтобы этого если есть хочу хотел меня тебя кому "
    "чего свой свою своя моей моих мной будет было была были всех всем очень через "
    "после перед также только сейчас здесь надо идут расскажи подскажи скажи узнать "
    "студент студенты студентов университет университета вуза вузе "
    # «где моя заявка» — вопрос про данные, а не про регламент
    "заявка заявки заявку заявок"
)


def _fallback(progress: _Progress, question: str) -> AssistantAnswer:
    """Ответ без модели: лучшие выдержки из найденных регламентов.

    Пометка обязательна — это не ответ модели, а цитата из базы знаний, и
    человек должен это видеть. Векторный поиск возвращает ближайшее даже на
    «какая погода», поэтому выдержка идёт в ответ, только если в ней есть
    слова вопроса: лучше честное «ничего не нашлось», чем чужой регламент.
    По выдержке на документ: соседние фрагменты перекрываются.

    Вопрос про свои данные («где моя заявка на справку») регламентом не
    отвечается: от него остаётся слово «справка», и выдержка пришла бы из
    справки для военкомата. Поэтому здесь — только кнопки к его данным.
    Обращение в деканат, если модель успела его создать, называется по номеру:
    оно уже в базе (tools._write_escalation).
    """
    own_data = tools_mod.asks_own_data(question)
    picked = [] if own_data else _pick_fragments(progress.fragments or [], question)

    escalated = ""
    if progress.escalations:
        numbers = ", ".join(f"№{n}" for n in progress.escalations)
        escalated = f"Вопрос уже передан в деканат — обращение {numbers}, ответ придёт в чат MAX."
    # Кнопки к данным студента — все, кроме кнопки самого обращения
    data_actions = [a for a in progress.actions if a.get("request_no") not in progress.escalations]
    buttons = ""
    if data_actions:
        buttons = "кнопке ниже" if len(data_actions) == 1 else "кнопкам ниже"

    if picked:
        blocks = "\n\n".join(f"«{f.title}»\n{_excerpt(f.text)}" for f in picked)
        tail = " ".join(
            part for part in (escalated, f"Твои данные — по {buttons}." if buttons else "") if part
        )
        text = f"{FALLBACK_NOTE}\n\n{blocks}\n\n"
        text += tail or "Если это не то — спроси ещё раз через минуту."
    elif escalated:
        text = f"Модель сейчас не ответила. {escalated}"
        if buttons:
            text += f" Твои данные — по {buttons}."
    elif buttons:
        text = f"Модель сейчас не ответила. Твои данные — по {buttons}, а вопрос можно повторить через минуту."
    elif own_data:
        text = (
            "Модель сейчас не ответила. Свои заявки и отклики — в разделах «Заявки» и «Люди», "
            "а вопрос можно повторить через минуту."
        )
    else:
        text = (
            "Модель сейчас не ответила, а в регламентах по этому вопросу ничего не нашлось. "
            "Спроси ещё раз через минуту — заявки, расписание и афиша работают как обычно."
        )

    return AssistantAnswer(
        text=text,
        sources=[
            {"title": f.title, "url": f.source_url, "snippet": f.text[:220]} for f in picked
        ],
        # Копия: запись обращения, не уложившаяся в срок, допишет кнопку в progress
        # позже — в уже собранный ответ без слов о ней она попасть не должна
        actions=list(progress.actions),
        tool_trace=list(progress.trace),
    )


def _pick_fragments(fragments: list[rag.Fragment], question: str) -> list[rag.Fragment]:
    """1–2 выдержки со словами вопроса: по одной на документ, вторая — только
    такая же сильная, как первая."""
    q_stems = _stems(question) - _STOP_STEMS
    need = 1 if len(q_stems) <= 2 else 2
    ranked: list[tuple[int, int, rag.Fragment]] = []
    for rank, frag in enumerate(fragments):
        hits = len(q_stems & _stems(f"{frag.title} {frag.text}"))
        if hits >= need:
            ranked.append((-hits, rank, frag))
    ranked.sort(key=lambda r: r[:2])

    picked: list[rag.Fragment] = []
    seen: set[int] = set()
    for neg_hits, _, frag in ranked:
        # Слабая выдержка «на всякий случай» уводит от ответа
        if neg_hits != ranked[0][0]:
            break
        if frag.document_id in seen:
            continue
        seen.add(frag.document_id)
        picked.append(frag)
        if len(picked) >= FALLBACK_FRAGMENTS:
            break
    return picked


def _dump_args(args: dict) -> str:
    return json.dumps(args, ensure_ascii=False)


async def _finalize(
    llm, messages: list[dict], tool_outputs: list[tuple[str, str]]
) -> str | None:
    """Просит модель сформулировать ответ по уже собранным данным, без инструментов.

    Данные дублируем простым текстом: модель заметно надёжнее читает их из
    обычного сообщения, чем из истории вызовов инструментов.
    None — модель не ответила: вызывающий отдаёт запасной ответ.
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
        return None
