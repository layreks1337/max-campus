"""Фоновые задачи.

Redis и отдельный планировщик сознательно не вводились: очередь живёт в Postgres,
задачи — обычные asyncio-циклы в lifespan приложения. Меньше сервисов в
docker-compose, меньше мест, где что-то может не подняться на демонстрации.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from app.core.dates import when_ru
from app.db.models import (
    REG_REGISTERED,
    AppUser,
    Binding,
    CalendarEvent,
    EventRegistration,
    Opportunity,
    OpportunityInterest,
    utcnow,
)
from app.db.session import SessionLocal
from app.modules.match.service import expire_intents, run_buddy_matcher
from app.modules.notify.service import enqueue

log = logging.getLogger("workers")


async def _student_max_ids(session, student_ids: list[int]) -> dict[int, int]:
    if not student_ids:
        return {}
    res = await session.execute(
        select(Binding.student_id, AppUser.max_user_id)
        .join(AppUser, AppUser.id == Binding.app_user_id)
        .where(Binding.student_id.in_(student_ids))
    )
    return {row[0]: row[1] for row in res.all()}


async def event_reminders() -> int:
    """Напоминания за 24 часа и за 1 час. Дедуп не даёт задвоить при рестарте."""
    sent = 0
    now = utcnow()
    async with SessionLocal() as session:
        for label, lo, hi in (
            ("24h", timedelta(hours=23), timedelta(hours=25)),
            ("1h", timedelta(minutes=45), timedelta(minutes=75)),
        ):
            res = await session.execute(
                select(CalendarEvent).where(
                    CalendarEvent.starts_at >= now + lo,
                    CalendarEvent.starts_at <= now + hi,
                    CalendarEvent.status == "PUBLISHED",
                )
            )
            events = list(res.scalars())
            for event in events:
                res = await session.execute(
                    select(EventRegistration).where(
                        EventRegistration.event_id == event.id,
                        EventRegistration.status == REG_REGISTERED,
                    )
                )
                regs = list(res.scalars())
                if not regs:
                    continue

                mapping = await _student_max_ids(session, [r.student_id for r in regs])
                when = when_ru(event.starts_at)
                head = "🔔 Завтра" if label == "24h" else "🔔 Через час"
                body = f"{head}\n\n{event.title}\n{when}"
                if event.location:
                    body += f"\n{event.location}"

                for reg in regs:
                    max_id = mapping.get(reg.student_id)
                    if not max_id:
                        continue
                    created = await enqueue(
                        session,
                        max_user_id=max_id,
                        kind="EVENT_REMINDER",
                        text=body,
                        dedup_key=f"evrem:{event.id}:{reg.student_id}:{label}",
                        open_app_label="Открыть календарь",
                        respect_quiet_hours=(label == "24h"),
                    )
                    if created:
                        sent += 1
        await session.commit()
    return sent


async def deadline_reminders() -> int:
    """Дедлайны возможностей за 7 и за 2 дня — тем, кто отметил интерес."""
    sent = 0
    now = utcnow()
    async with SessionLocal() as session:
        for label, days in (("7d", 7), ("2d", 2)):
            res = await session.execute(
                select(Opportunity).where(
                    Opportunity.registration_deadline >= now + timedelta(days=days),
                    Opportunity.registration_deadline
                    <= now + timedelta(days=days, hours=24),
                    Opportunity.moderation_status == "APPROVED",
                )
            )
            for opp in res.scalars():
                res2 = await session.execute(
                    select(OpportunityInterest).where(
                        OpportunityInterest.opportunity_id == opp.id,
                        OpportunityInterest.level == "INTERESTED",
                    )
                )
                interests = list(res2.scalars())
                if not interests:
                    continue

                mapping = await _student_max_ids(session, [i.student_id for i in interests])
                word = "через неделю" if label == "7d" else "через 2 дня"
                text = (
                    f"⏳ Регистрация закрывается {word}\n\n"
                    f"{opp.title}\n{opp.organizer}"
                )
                if opp.prize_text:
                    text += f"\n{opp.prize_text}"

                for interest in interests:
                    max_id = mapping.get(interest.student_id)
                    if not max_id:
                        continue
                    created = await enqueue(
                        session,
                        max_user_id=max_id,
                        kind="OPPORTUNITY_DEADLINE",
                        text=text,
                        dedup_key=f"oppdl:{opp.id}:{interest.student_id}:{label}",
                        open_app_label="Открыть возможности",
                        respect_quiet_hours=True,
                    )
                    if created:
                        sent += 1
        await session.commit()
    return sent


async def class_reminders() -> int:
    """За 15 минут до первой пары дня — куда идти. Только первая пара:
    напоминание перед каждой превратилось бы в спам и его бы отключили."""
    from app.core.dates import UNIVERSITY_TZ
    from app.db.models import ScheduleSlot, Student

    sent = 0
    now_local = utcnow().astimezone(UNIVERSITY_TZ)
    minutes = now_local.hour * 60 + now_local.minute
    today = now_local.date()
    week_no = max(1, (today - _academic_start(today)).days // 7 + 1)
    parity = "odd" if week_no % 2 else "even"

    async with SessionLocal() as session:
        res = await session.execute(
            select(ScheduleSlot).where(ScheduleSlot.weekday == today.weekday())
            .order_by(ScheduleSlot.group_name, ScheduleSlot.pair_no)
        )
        first: dict[str, ScheduleSlot] = {}
        for slot in res.scalars():
            if slot.parity in ("any", parity):
                first.setdefault(slot.group_name, slot)

        for group, slot in first.items():
            h, m = slot.starts.split(":")
            until = int(h) * 60 + int(m) - minutes
            if not 5 <= until <= 20:
                continue
            res = await session.execute(
                select(AppUser.max_user_id, Student.id)
                .join(Binding, Binding.app_user_id == AppUser.id)
                .join(Student, Student.id == Binding.student_id)
                .where(Student.group_name == group)
            )
            place = f"ауд. {slot.room}" if slot.room[:1].isdigit() else slot.room
            text = f"📚 Через {until} мин — {slot.subject}\n{slot.kind} · {place} · {slot.starts}"
            for max_id, student_id in res.all():
                created = await enqueue(
                    session, max_user_id=max_id, kind="CLASS_REMINDER", text=text,
                    dedup_key=f"class:{student_id}:{today.isoformat()}",
                    open_app_label="Расписание",
                )
                if created:
                    sent += 1
        await session.commit()
    return sent


def _academic_start(d):
    from datetime import date

    year = d.year if d.month >= 9 else d.year - 1
    start = date(year, 9, 1)
    return start - timedelta(days=start.weekday())


async def buddy_and_cleanup() -> None:
    async with SessionLocal() as session:
        try:
            await run_buddy_matcher(session)
            await expire_intents(session)
            await session.commit()
        except Exception:
            await session.rollback()
            log.exception("Сбой в buddy/cleanup")


async def _loop(name: str, coro, interval: float) -> None:
    log.info("Фоновая задача «%s» запущена (интервал %ss)", name, interval)
    # разносим старты, чтобы не бить по БД одновременно
    await asyncio.sleep(5)
    while True:
        try:
            await coro()
        except asyncio.CancelledError:
            log.info("Фоновая задача «%s» остановлена", name)
            raise
        except Exception:
            log.exception("Сбой в фоновой задаче «%s»", name)
        await asyncio.sleep(interval)


def start_background_tasks() -> list[asyncio.Task]:
    from app.modules.notify.service import outbox_worker

    return [
        asyncio.create_task(outbox_worker(interval=3.0), name="outbox"),
        asyncio.create_task(_loop("event_reminders", event_reminders, 300), name="reminders"),
        asyncio.create_task(
            _loop("deadline_reminders", deadline_reminders, 3600), name="deadlines"
        ),
        asyncio.create_task(_loop("buddy", buddy_and_cleanup, 1800), name="buddy"),
        asyncio.create_task(_loop("class_reminders", class_reminders, 240), name="classes"),
    ]
