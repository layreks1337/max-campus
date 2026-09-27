"""Инструменты ассистента.

Два жёстких правила (решения 012 и 013):

1. Авторизация живёт в слое исполнения, а не у модели. student_id берётся из
   контекста вызова, и в схеме инструмента поля «чей» физически нет. Иначе
   «покажи заявки Иванова» становится рабочим эксплойтом.

2. Инструменты ничего не совершают молча. Там, где нужно действие, возвращается
   UI-действие — кнопка, которую нажмёт человек. Галлюцинация не должна уметь
   подать заявление на академический отпуск.

search_regulations здесь СОЗНАТЕЛЬНО отсутствует: поиск по регламентам выполняется
принудительно до вызова модели (решение 019).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    ACTIVE_STATUSES,
    MOD_APPROVED,
    STATUS_TITLES,
    CalendarEvent,
    Intent,
    MatchPair,
    Opportunity,
    Request,
    RequestTemplate,
    Student,
    utcnow,
)
from app.db.session import SessionLocal

log = logging.getLogger("assistant.tools")

# Ссылки на фоновые записи: без них задачу, чьего ожидающего отменил таймаут,
# может подобрать сборщик мусора посреди записи
_background: set[asyncio.Task] = set()


@dataclass
class ToolContext:
    session: AsyncSession
    student: Student
    app_user_id: int
    ui_actions: list[dict] = field(default_factory=list)
    called: list[str] = field(default_factory=list)
    # Результаты уже выполненных вызовов в пределах одного вопроса.
    # Предзапрос часто достаёт то же, что потом просит модель, — второй поход
    # в базу за тем же самым не нужен.
    cache: dict[str, str] = field(default_factory=dict)
    # Обращения в деканат, созданные за этот вопрос (номера), и задачи их записи:
    # по таймауту сервис дожидается записи, чтобы назвать студенту номер
    escalations: list[str] = field(default_factory=list)
    writes: list[asyncio.Task] = field(default_factory=list)

    def add_action(self, action: dict) -> None:
        if action not in self.ui_actions:
            self.ui_actions.append(action)


# ── Описания для модели ───────────────────────────────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_my_requests",
            "description": (
                "Заявки текущего студента и их статусы. Вызывай, когда спрашивают "
                "про «мою справку», «мою заявку», «где моё заявление», «готово ли»."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "only_active": {
                        "type": "boolean",
                        "description": "Только заявки в работе, без завершённых",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_request_templates",
            "description": (
                "Список доступных справок и заявлений, которые можно оформить. "
                "Вызывай, когда спрашивают «какие справки бывают», «что можно заказать»."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_request",
            "description": (
                "Предложить студенту оформить конкретную справку. НЕ создаёт заявку — "
                "возвращает кнопку, форму заполняет человек. Сначала узнай ключ "
                "через list_request_templates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "template_key": {
                        "type": "string",
                        "description": "Ключ шаблона, например study_certificate",
                    }
                },
                "required": ["template_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": (
                "Ближайшие события вуза для этого студента с учётом его факультета и курса. "
                "Вызывай на вопросы «что интересного», «какие собрания», «что на неделе»."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Горизонт в днях, по умолчанию 14",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_opportunities",
            "description": (
                "Хакатоны, конкурсы, олимпиады, стажировки с открытой регистрацией. "
                "Вызывай на «куда можно поучаствовать», «какие хакатоны», «конкурсы»."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "description": "HACKATHON, CONTEST, OLYMPIAD, CONFERENCE, "
                        "GRANT, INTERNSHIP или VOLUNTEER",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_matches",
            "description": (
                "Отклики и найденные напарники студента в разделе «Люди». "
                "Вызывай на «кто мне ответил», «мои матчи»."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": (
                "КРАЙНЯЯ МЕРА. Создаёт обращение к сотруднику деканата. "
                "Вызывай ТОЛЬКО если уже попробовал подходящий инструмент и он не дал "
                "ответа, а в выдержках регламентов ничего нет. "
                "НИКОГДА не вызывай первым. Вопросы вида «где моя заявка», «готова ли "
                "справка» решаются инструментом get_my_requests, а не этим."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Формулировка вопроса для сотрудника",
                    }
                },
                "required": ["question"],
            },
        },
    },
]

# Подсказки модели, если она полезла в эскалацию раньше времени
_ESCALATION_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("заявк", "справк", "заявлен", "статус", "готов"), "get_my_requests"),
    (("событи", "собрани", "меропри", "календар"), "list_events"),
    (("хакатон", "конкурс", "олимпиад", "стажиров", "грант"), "list_opportunities"),
    (("отклик", "матч", "наставник", "напарник"), "get_my_matches"),
    (("оформ", "заказать", "получить справку"), "list_request_templates"),
]


# ── Детерминированный предзапрос ──────────────────────────────────
#
# Та же логика, что и с принудительным RAG (решение 019): модель нельзя
# заставить надёжно вызвать нужный инструмент. На вопросе «какие идут
# хакатоны?» она однажды не вызвала ничего и ВЫДУМАЛА три несуществующих
# мероприятия. Поэтому очевидные по формулировке данные подтягиваем сами
# и кладём в контекст ещё до обращения к модели. Инструменты при этом
# остаются доступными — предзапрос их не заменяет, а страхует.

PREFETCH_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (
        ("хакатон", "конкурс", "олимпиад", "стажиров", "грант", "волонтёр", "волонтер",
         "возможност", "поучаствовать", "куда пойти", "соревнован"),
        "list_opportunities",
        "Актуальные возможности (хакатоны, конкурсы, стажировки)",
    ),
    (
        ("событи", "собрани", "меропри", "календар", "на этой неделе", "интересного",
         "afisha", "афиш", "что будет"),
        "list_events",
        "Ближайшие события вуза для этого студента",
    ),
    (
        ("моя заявк", "мои заявк", "мою заявк", "моей заявк", "моя справк", "мою справк",
         "где заявк", "где справк", "готова ли", "готово ли", "статус заявк",
         "статус справк", "что с заявк", "что со справк"),
        "get_my_requests",
        "Заявки этого студента",
    ),
    (
        ("какие справк", "что можно заказать", "какие заявлен", "какие документ",
         "что можно оформить", "список справок"),
        "list_request_templates",
        "Доступные шаблоны заявок",
    ),
    (
        ("отклик", "мои матч", "наставник", "напарник", "знакомств", "кто ответил"),
        "get_my_matches",
        "Отклики и напарники этого студента",
    ),
]


# Инструменты, которые читают собственные данные студента, а не справочники
OWN_DATA_TOOLS = ("get_my_requests", "get_my_matches")


def asks_own_data(question: str) -> bool:
    """Вопрос про свои заявки или отклики — ответ в данных студента, не в регламенте."""
    low = question.lower()
    return any(
        tool_name in OWN_DATA_TOOLS and any(kw in low for kw in keywords)
        for keywords, tool_name, _ in PREFETCH_RULES
    )


async def prefetch(ctx: ToolContext, question: str) -> list[tuple[str, str]]:
    """Подтягивает данные, очевидно нужные по формулировке вопроса.

    Возвращает список (заголовок блока, содержимое) для системного сообщения.
    """
    low = question.lower()
    blocks: list[tuple[str, str]] = []
    for keywords, tool_name, title in PREFETCH_RULES:
        if not any(kw in low for kw in keywords):
            continue
        if tool_name not in HANDLERS:
            continue
        try:
            # Через dispatch, а не напрямую: результат попадает в кеш, и если
            # модель потом вызовет тот же инструмент, второго похода в базу не будет.
            output = await dispatch(ctx, tool_name, {})
            blocks.append((title, output))
            log.info("Предзапрос %s по формулировке вопроса", tool_name)
        except Exception:
            log.exception("Предзапрос %s не удался", tool_name)
    return blocks


# ── Реализация ────────────────────────────────────────────────────


async def _get_my_requests(ctx: ToolContext, only_active: bool = False) -> str:
    stmt = select(Request).where(Request.student_id == ctx.student.id)
    if only_active:
        stmt = stmt.where(Request.status.in_(ACTIVE_STATUSES))
    # selectinload обязателен: ниже читается r.document, а ленивая загрузка
    # связи в async-контексте поднимает MissingGreenlet и роняет инструмент.
    stmt = (
        stmt.options(selectinload(Request.document))
        .order_by(Request.created_at.desc())
        .limit(10)
    )

    rows = list((await ctx.session.execute(stmt)).scalars())
    if not rows:
        return json.dumps(
            {
                "requests": [],
                "count": 0,
                "note": "Студент пока не подавал ни одной заявки. Это не ошибка — "
                        "так и скажи, и предложи оформить справку.",
            },
            ensure_ascii=False,
        )

    items = []
    for i, r in enumerate(rows):
        items.append(
            {
                "number": r.public_no,
                "title": r.template.short_title or r.template.title,
                "status": STATUS_TITLES.get(r.status, r.status),
                "status_code": r.status,
                "submitted": r.created_at.strftime("%d.%m.%Y"),
                "due": r.due_at.strftime("%d.%m.%Y") if r.due_at else None,
                "has_document": r.document is not None,
            }
        )
        # Кнопок не больше трёх: под ответом ассистента ряд из десяти
        # одинаковых пилюль выглядит как сбой, а не как помощь.
        if i < 3:
            ctx.add_action(
                {
                    "type": "open_request",
                    "label": f"Заявка №{r.public_no}",
                    "request_no": r.public_no,
                }
            )
    return json.dumps({"requests": items, "count": len(items)}, ensure_ascii=False)


async def _list_request_templates(ctx: ToolContext) -> str:
    rows = list(
        (
            await ctx.session.execute(
                select(RequestTemplate)
                .where(RequestTemplate.active.is_(True))
                .order_by(RequestTemplate.sort_order)
            )
        ).scalars()
    )
    items = [
        {
            "key": t.key,
            "title": t.title,
            "description": t.description,
            "days": round((t.sla_hours or 72) / 24),
            # иначе модель пообещает «3 дня» там, где справка выдаётся сразу
            **(
                {"issued": "сразу при подаче, автоматически; с оригиналом или "
                           "особыми требованиями — через сотрудника, в обычный срок"}
                if t.auto_issue else {}
            ),
        }
        for t in rows
    ]
    return json.dumps({"templates": items}, ensure_ascii=False)


async def _start_request(ctx: ToolContext, template_key: str) -> str:
    tpl = await ctx.session.get(RequestTemplate, template_key)
    if tpl is None or not tpl.active:
        return json.dumps(
            {"error": f"Шаблон «{template_key}» не найден. Возьми ключ из list_request_templates"},
            ensure_ascii=False,
        )
    ctx.add_action(
        {"type": "open_request_form", "label": f"Оформить: {tpl.short_title or tpl.title}",
         "template_key": tpl.key}
    )
    return json.dumps(
        {
            "ok": True,
            "template": tpl.title,
            "days": round((tpl.sla_hours or 72) / 24),
            "note": "Кнопка для перехода к форме уже показана студенту. "
                    "Заявка НЕ создана — её заполнит человек.",
        },
        ensure_ascii=False,
    )


def _audience_matches(audience: dict, student: Student) -> bool:
    if not audience:
        return True
    fac = audience.get("faculties") or []
    if fac and student.faculty not in fac:
        return False
    courses = audience.get("courses") or []
    if courses and student.course not in courses:
        return False
    groups = audience.get("groups") or []
    if groups and student.group_name not in groups:
        return False
    if audience.get("only_freshmen") and student.course != 1:
        return False
    return True


async def _list_events(ctx: ToolContext, days: int = 14) -> str:
    now = utcnow()
    horizon = now + timedelta(days=max(1, min(days, 90)))
    rows = list(
        (
            await ctx.session.execute(
                select(CalendarEvent)
                .where(
                    CalendarEvent.starts_at >= now,
                    CalendarEvent.starts_at <= horizon,
                    CalendarEvent.status == "PUBLISHED",
                )
                .order_by(CalendarEvent.starts_at)
                .limit(30)
            )
        ).scalars()
    )
    items = []
    for e in rows:
        if not _audience_matches(e.audience_json or {}, ctx.student):
            continue
        items.append(
            {
                "id": e.id,
                "title": e.title,
                "when": e.starts_at.strftime("%d.%m %H:%M"),
                "location": e.location,
                "needs_registration": e.registration_required,
            }
        )
    if items:
        ctx.add_action({"type": "open_events", "label": "Открыть календарь"})
    return json.dumps({"events": items[:10]}, ensure_ascii=False)


async def _list_opportunities(ctx: ToolContext, kind: str | None = None) -> str:
    stmt = select(Opportunity).where(Opportunity.moderation_status == MOD_APPROVED)
    if kind:
        stmt = stmt.where(Opportunity.kind == kind.upper())
    stmt = stmt.order_by(Opportunity.registration_deadline.asc().nullslast()).limit(10)

    rows = list((await ctx.session.execute(stmt)).scalars())
    items = [
        {
            "id": o.id,
            "title": o.title,
            "kind": o.kind,
            "organizer": o.organizer,
            "deadline": o.registration_deadline.strftime("%d.%m.%Y")
            if o.registration_deadline
            else None,
            "team": f"{o.team_size_min}–{o.team_size_max}" if o.team_size_max > 1 else "лично",
            "prize": o.prize_text,
        }
        for o in rows
    ]
    if items:
        ctx.add_action({"type": "open_opportunities", "label": "Смотреть все возможности"})
    return json.dumps({"opportunities": items}, ensure_ascii=False)


async def _get_my_matches(ctx: ToolContext) -> str:
    rows = list(
        (
            await ctx.session.execute(
                select(MatchPair)
                .where(
                    (MatchPair.a_user_id == ctx.app_user_id)
                    | (MatchPair.b_user_id == ctx.app_user_id)
                )
                .order_by(MatchPair.created_at.desc())
                .limit(10)
            )
        ).scalars()
    )
    if not rows:
        return json.dumps(
            {"matches": [], "note": "Пока нет откликов. Можно полистать колоду в разделе «Люди»."},
            ensure_ascii=False,
        )

    items = []
    for m in rows:
        intent = await ctx.session.get(Intent, m.intent_id) if m.intent_id else None
        items.append(
            {
                "origin": "Наставник" if m.origin == "BUDDY" else "Отклик",
                "about": intent.title if intent else "Знакомство",
                "when": m.created_at.strftime("%d.%m"),
            }
        )
    ctx.add_action({"type": "open_matches", "label": "Открыть мои отклики"})
    return json.dumps({"matches": items}, ensure_ascii=False)


async def _escalate_to_human(ctx: ToolContext, question: str) -> str:
    # Защита от преждевременной эскалации: модель склонна дёргать этот инструмент
    # первым, и тогда вместо ответа про собственную заявку студент получает
    # обращение в деканат. Если по формулировке видно подходящий инструмент,
    # а он ещё не вызывался — возвращаем подсказку вместо создания обращения.
    others = [name for name in ctx.called if name != "escalate_to_human"]
    if not others:
        low = question.lower()
        for keywords, suggested in _ESCALATION_HINTS:
            if any(kw in low for kw in keywords):
                return json.dumps(
                    {
                        "error": "Слишком рано для обращения в деканат.",
                        "do_this_instead": suggested,
                        "note": f"Сначала вызови {suggested} — ответ, скорее всего, есть там.",
                    },
                    ensure_ascii=False,
                )

    # Обращение пишется в своей сессии и коммитится сразу (решение 061). Ответ
    # ассистента ограничен по времени, и по таймауту его транзакция откатывается —
    # обращение пропало бы вместе с ней, а кнопка к нему осталась бы в ответе.
    # shield: отмена по таймауту не обрывает запись посередине, сервис её дождётся.
    task = asyncio.ensure_future(_write_escalation(ctx, ctx.student.id, question))
    _background.add(task)
    task.add_done_callback(_background.discard)
    ctx.writes.append(task)

    public_no = await asyncio.shield(task)
    if public_no is None:
        return json.dumps({"error": "Канал обращений недоступен"}, ensure_ascii=False)
    return json.dumps(
        {
            "ok": True,
            "number": public_no,
            "note": "Вопрос передан в деканат. Ответ придёт в чат MAX.",
        },
        ensure_ascii=False,
    )


async def _write_escalation(ctx: ToolContext, student_id: int, question: str) -> str | None:
    """Создаёт обращение и коммитит его. Номер — или None, если записать не вышло.

    student_id передаётся числом: к этому моменту основная сессия могла уже
    откатиться по таймауту, и чтение атрибута ctx.student полезло бы в неё.
    """
    from app.modules.requests.engine import create_request

    try:
        async with SessionLocal() as session:
            tpl = await session.get(RequestTemplate, "support_question")
            student = await session.get(Student, student_id)
            if tpl is None or student is None:
                return None
            req = await create_request(
                session,
                template=tpl,
                student=student,
                payload={"question": question[:1000], "source": "Ассистент"},
            )
            await session.commit()
    except Exception:
        log.exception("Не удалось создать обращение в деканат")
        return None

    # Кнопка — только когда обращение уже в базе
    ctx.escalations.append(req.public_no)
    ctx.add_action(
        {"type": "open_request", "label": f"Обращение №{req.public_no}",
         "request_no": req.public_no}
    )
    return req.public_no


HANDLERS = {
    "get_my_requests": _get_my_requests,
    "list_request_templates": _list_request_templates,
    "start_request": _start_request,
    "list_events": _list_events,
    "list_opportunities": _list_opportunities,
    "get_my_matches": _get_my_matches,
    "escalate_to_human": _escalate_to_human,
}


async def dispatch(ctx: ToolContext, name: str, arguments: dict[str, Any]) -> str:
    handler = HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Неизвестный инструмент {name}"}, ensure_ascii=False)

    # Эскалация создаёт обращение, её кешировать нельзя
    cache_key = f"{name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"
    if name != "escalate_to_human" and cache_key in ctx.cache:
        log.debug("Повторный вызов %s — отдаём из кеша", name)
        return ctx.cache[cache_key]

    ctx.called.append(name)
    try:
        result = await handler(ctx, **arguments)
        ctx.cache[cache_key] = result
        return result
    except TypeError:
        # модель прислала лишние или неверные аргументы — пробуем без них
        try:
            return await handler(ctx)
        except Exception:
            log.exception("Инструмент %s упал", name)
            return json.dumps({"error": "Инструмент недоступен"}, ensure_ascii=False)
    except Exception:
        log.exception("Инструмент %s упал", name)
        return json.dumps({"error": "Инструмент недоступен"}, ensure_ascii=False)
