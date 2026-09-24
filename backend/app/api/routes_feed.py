"""Календарь вуза и возможности (хакатоны, конкурсы, стажировки)."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, text as sql_text

from app.api import serializers
from app.api.schemas import (
    EventCreateIn,
    EventOut,
    InterestIn,
    IntentOut,
    LookingForTeamIn,
    Ok,
    OpportunityCreateIn,
    OpportunityOut,
)
from app.core.dates import when_ru
from app.core.deps import BoundUserDep, SessionDep, StaffUserDep
from app.db.models import (
    MOD_APPROVED,
    MOD_PENDING,
    REG_CANCELLED,
    REG_REGISTERED,
    REG_WAITLIST,
    CalendarEvent,
    EventRegistration,
    Intent,
    Opportunity,
    OpportunityInterest,
    utcnow,
)
from app.modules.feed.scoring import score_opportunity
from app.modules.match.service import audience_matches
from app.modules.notify.service import enqueue

log = logging.getLogger("api.feed")
events_router = APIRouter(prefix="/events", tags=["events"])
opps_router = APIRouter(prefix="/opportunities", tags=["opportunities"])


# ══════════════════════════════════════════════════════════════════
#  События
# ══════════════════════════════════════════════════════════════════


@events_router.get("", response_model=list[EventOut], summary="Календарь вуза")
async def list_events(
    current: BoundUserDep,
    session: SessionDep,
    days: int = Query(60, ge=1, le=365),
) -> list[EventOut]:
    now = utcnow()
    res = await session.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.starts_at >= now - timedelta(hours=6),
            CalendarEvent.starts_at <= now + timedelta(days=days),
            CalendarEvent.status == "PUBLISHED",
        )
        .order_by(CalendarEvent.starts_at)
        .limit(200)
    )
    events = [e for e in res.scalars() if audience_matches(e.audience_json or {}, current.student)]
    if not events:
        return []

    ids = [e.id for e in events]
    res = await session.execute(
        select(EventRegistration.event_id, func.count(EventRegistration.id))
        .where(
            EventRegistration.event_id.in_(ids), EventRegistration.status == REG_REGISTERED
        )
        .group_by(EventRegistration.event_id)
    )
    taken = {row[0]: row[1] for row in res.all()}

    res = await session.execute(
        select(EventRegistration).where(
            EventRegistration.event_id.in_(ids),
            EventRegistration.student_id == current.student.id,
        )
    )
    mine = {r.event_id: r.status for r in res.scalars()}

    return [serializers.event_out(e, taken.get(e.id, 0), mine.get(e.id)) for e in events]


@events_router.post("/{event_id}/register", response_model=EventOut, summary="Записаться")
async def register_event(
    event_id: int, current: BoundUserDep, session: SessionDep
) -> EventOut:
    """Место занимается в транзакции — иначе гонка за последний слот."""
    # Блокируем строку события: без этого два параллельных запроса займут одно место
    await session.execute(
        sql_text("SELECT id FROM calendar_event WHERE id = :eid FOR UPDATE"), {"eid": event_id}
    )
    event = await session.get(CalendarEvent, event_id)
    if event is None or event.status != "PUBLISHED":
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Событие не найдено"})

    if event.registration_deadline and event.registration_deadline < utcnow():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "REGISTRATION_CLOSED", "message": "Регистрация закрыта"},
        )

    res = await session.execute(
        select(EventRegistration).where(
            EventRegistration.event_id == event_id,
            EventRegistration.student_id == current.student.id,
        )
    )
    reg = res.scalar_one_or_none()

    if reg is not None and reg.status in (REG_REGISTERED, REG_WAITLIST):
        return await _event_payload(session, event, current.student.id)

    res = await session.execute(
        select(func.count(EventRegistration.id)).where(
            EventRegistration.event_id == event_id,
            EventRegistration.status == REG_REGISTERED,
        )
    )
    taken = res.scalar() or 0
    new_status = (
        REG_WAITLIST if event.capacity and taken >= event.capacity else REG_REGISTERED
    )

    if reg is None:
        session.add(
            EventRegistration(
                event_id=event_id, student_id=current.student.id, status=new_status
            )
        )
    else:
        reg.status = new_status
    await session.flush()

    when = when_ru(event.starts_at)
    if new_status == REG_REGISTERED:
        body = f"Место забронировано.\n{when}"
        if event.location:
            body += f"\n{event.location}"
    else:
        body = f"Мест не осталось — ты в списке ожидания.\nСообщу, если место освободится.\n{when}"

    await enqueue(
        session,
        max_user_id=current.app_user.max_user_id,
        kind="EVENT_REGISTERED",
        text=f"📅 {event.title}\n\n{body}",
        dedup_key=f"evreg:{event_id}:{current.student.id}:{new_status}",
        open_app_label="Открыть календарь",
    )
    return await _event_payload(session, event, current.student.id)


@events_router.delete("/{event_id}/register", response_model=EventOut, summary="Отменить запись")
async def unregister_event(
    event_id: int, current: BoundUserDep, session: SessionDep
) -> EventOut:
    res = await session.execute(
        select(EventRegistration).where(
            EventRegistration.event_id == event_id,
            EventRegistration.student_id == current.student.id,
        )
    )
    reg = res.scalar_one_or_none()
    event = await session.get(CalendarEvent, event_id)
    if reg is None or event is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Запись не найдена"})

    was_registered = reg.status == REG_REGISTERED
    reg.status = REG_CANCELLED
    await session.flush()

    # Освободилось место — поднимаем первого из листа ожидания
    if was_registered and event.capacity:
        res = await session.execute(
            select(EventRegistration)
            .where(
                EventRegistration.event_id == event_id,
                EventRegistration.status == REG_WAITLIST,
            )
            .order_by(EventRegistration.created_at)
            .limit(1)
        )
        promoted = res.scalar_one_or_none()
        if promoted is not None:
            promoted.status = REG_REGISTERED
            await session.flush()
            max_id = await _student_max_user_id(session, promoted.student_id)
            if max_id:
                await enqueue(
                    session,
                    max_user_id=max_id,
                    kind="WAITLIST_PROMOTED",
                    text=(
                        f"🎟 Место освободилось!\n\n{event.title}\n"
                        f"{when_ru(event.starts_at)}\n"
                        "Ты записан(а)."
                    ),
                    dedup_key=f"promote:{event_id}:{promoted.student_id}",
                    open_app_label="Открыть календарь",
                )

    return await _event_payload(session, event, current.student.id)


@events_router.post("", response_model=EventOut, status_code=201, summary="Создать событие")
async def create_event(
    body: EventCreateIn, current: StaffUserDep, session: SessionDep
) -> EventOut:
    event = CalendarEvent(
        title=body.title,
        description=body.description,
        kind=body.kind,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        location=body.location,
        cover_url=body.cover_url,
        capacity=body.capacity,
        registration_required=body.registration_required,
        audience_json=body.audience,
        organizer_name=current.staff.full_name,
        status="PUBLISHED",
    )
    session.add(event)
    await session.flush()
    return serializers.event_out(event, 0, None)


async def _event_payload(session, event: CalendarEvent, student_id: int) -> EventOut:
    res = await session.execute(
        select(func.count(EventRegistration.id)).where(
            EventRegistration.event_id == event.id,
            EventRegistration.status == REG_REGISTERED,
        )
    )
    taken = res.scalar() or 0
    res = await session.execute(
        select(EventRegistration).where(
            EventRegistration.event_id == event.id,
            EventRegistration.student_id == student_id,
        )
    )
    reg = res.scalar_one_or_none()
    return serializers.event_out(event, taken, reg.status if reg else None)


async def _student_max_user_id(session, student_id: int) -> int | None:
    from app.db.models import AppUser, Binding

    res = await session.execute(
        select(AppUser.max_user_id)
        .join(Binding, Binding.app_user_id == AppUser.id)
        .where(Binding.student_id == student_id)
    )
    return res.scalar_one_or_none()


# ══════════════════════════════════════════════════════════════════
#  Возможности
# ══════════════════════════════════════════════════════════════════


@opps_router.get("", response_model=list[OpportunityOut], summary="Лента возможностей")
async def list_opportunities(
    current: BoundUserDep,
    session: SessionDep,
    kind: str | None = Query(None),
    mine: bool = Query(False, description="Только мои предложения"),
) -> list[OpportunityOut]:
    stmt = select(Opportunity)
    if mine:
        stmt = stmt.where(Opportunity.author_user_id == current.app_user.id)
    else:
        stmt = stmt.where(Opportunity.moderation_status == MOD_APPROVED)
    if kind:
        stmt = stmt.where(Opportunity.kind == kind.upper())

    res = await session.execute(stmt.limit(200))
    opps = list(res.scalars())
    if not opps:
        return []

    res = await session.execute(
        select(OpportunityInterest).where(
            OpportunityInterest.student_id == current.student.id
        )
    )
    mine_map = {i.opportunity_id: i.level for i in res.scalars()}

    # Социальный сигнал: сколько однокурсников отметились
    res = await session.execute(
        select(OpportunityInterest.opportunity_id, func.count(OpportunityInterest.id))
        .where(OpportunityInterest.opportunity_id.in_([o.id for o in opps]))
        .group_by(OpportunityInterest.opportunity_id)
    )
    peers = {row[0]: row[1] for row in res.all()}

    scored = [
        (
            o,
            score_opportunity(o, current.student, peers_interested=peers.get(o.id, 0)),
        )
        for o in opps
    ]
    scored.sort(key=lambda p: p[1], reverse=True)
    return [serializers.opportunity_out(o, mine_map.get(o.id), sc) for o, sc in scored]


@opps_router.post("", response_model=OpportunityOut, status_code=201, summary="Предложить своё")
async def create_opportunity(
    body: OpportunityCreateIn, current: BoundUserDep, session: SessionDep
) -> OpportunityOut:
    """Пользовательский контент уходит на модерацию — иначе спам и реклама."""
    is_staff = current.is_staff
    opp = Opportunity(
        title=body.title,
        description=body.description,
        kind=body.kind.upper(),
        level=body.level.upper(),
        organizer=body.organizer or current.student.full_name,
        url=body.url,
        registration_deadline=body.registration_deadline,
        team_size_min=body.team_size_min,
        team_size_max=body.team_size_max,
        prize_text=body.prize_text,
        tags=body.tags,
        source="STAFF" if is_staff else "STUDENT",
        author_user_id=current.app_user.id,
        moderation_status=MOD_APPROVED if is_staff else MOD_PENDING,
    )
    session.add(opp)
    await session.flush()
    return serializers.opportunity_out(opp, None, 0.0)


@opps_router.post("/{opp_id}/interest", response_model=Ok, summary="Отметить интерес")
async def set_interest(
    opp_id: int, body: InterestIn, current: BoundUserDep, session: SessionDep
) -> Ok:
    opp = await session.get(Opportunity, opp_id)
    if opp is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Не найдено"})

    res = await session.execute(
        select(OpportunityInterest).where(
            OpportunityInterest.opportunity_id == opp_id,
            OpportunityInterest.student_id == current.student.id,
        )
    )
    interest = res.scalar_one_or_none()
    if interest is None:
        session.add(
            OpportunityInterest(
                opportunity_id=opp_id, student_id=current.student.id, level=body.level
            )
        )
    else:
        interest.level = body.level
    await session.flush()
    return Ok()


@opps_router.post(
    "/{opp_id}/looking-for-team", response_model=IntentOut, summary="Ищу команду"
)
async def looking_for_team(
    opp_id: int, body: LookingForTeamIn, current: BoundUserDep, session: SessionDep
) -> IntentOut:
    """Стыковка двух модулей: возможность порождает карточку в колоде матчинга."""
    opp = await session.get(Opportunity, opp_id)
    if opp is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Не найдено"})

    intent = Intent(
        author_user_id=current.app_user.id,
        kind="TEAM",
        title=f"Ищу команду: {opp.title}",
        description=body.message
        or f"Собираю команду на «{opp.title}». Нужно {opp.team_size_min}–{opp.team_size_max} человек.",
        tags=list(opp.tags or []),
        opportunity_id=opp.id,
        expires_at=opp.registration_deadline or (utcnow() + timedelta(days=21)),
    )
    session.add(intent)
    await session.flush()
    await session.refresh(intent, ["author", "opportunity"])
    return serializers.intent_out(intent, current.student, 0.0)


# ── Модерация ─────────────────────────────────────────────────────

moderation_router = APIRouter(prefix="/moderation", tags=["moderation"])


@moderation_router.get("/queue", response_model=list[OpportunityOut], summary="Очередь модерации")
async def moderation_queue(
    current: StaffUserDep, session: SessionDep
) -> list[OpportunityOut]:
    res = await session.execute(
        select(Opportunity)
        .where(Opportunity.moderation_status == MOD_PENDING)
        .order_by(Opportunity.created_at)
    )
    return [serializers.opportunity_out(o) for o in res.scalars()]


@moderation_router.post("/{opp_id}/decide", response_model=Ok, summary="Решение модератора")
async def moderate(
    opp_id: int,
    approve: bool,
    current: StaffUserDep,
    session: SessionDep,
) -> Ok:
    opp = await session.get(Opportunity, opp_id)
    if opp is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Не найдено"})
    opp.moderation_status = MOD_APPROVED if approve else "REJECTED"
    opp.moderated_by = current.staff.full_name
    opp.moderated_at = utcnow()
    await session.flush()
    return Ok()
