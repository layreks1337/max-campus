"""Профиль, привязка студенческого, загрузка файлов, главный экран."""

from __future__ import annotations

import logging
import time
import uuid as uuid_lib
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api import serializers
from app.api.schemas import (
    BindRequest,
    HomeOut,
    MeOut,
    StaffOut,
)
from app.core.config import settings
from app.core.deps import BoundUserDep, CurrentUserDep, SessionDep
from app.db.models import (
    ACTIVE_STATUSES,
    MOD_APPROVED,
    REG_REGISTERED,
    Binding,
    BindingCode,
    CalendarEvent,
    EventRegistration,
    Intent,
    MatchPair,
    Opportunity,
    OpportunityInterest,
    Request,
    Student,
    Swipe,
    utcnow,
)
from app.modules.feed.scoring import score_opportunity
from app.modules.match.service import audience_matches

log = logging.getLogger("api.core")
router = APIRouter(tags=["core"])

# Ограничение попыток ввода кода: иначе подбирается за минуту
_attempts: dict[int, list[float]] = defaultdict(list)
_MAX_ATTEMPTS = 5
_WINDOW = 3600.0


@router.get("/me", response_model=MeOut, summary="Профиль текущего пользователя")
async def get_me(current: CurrentUserDep) -> MeOut:
    return MeOut(
        max_user_id=current.app_user.max_user_id,
        display_name=current.display_name,
        photo_url=current.app_user.photo_url or "",
        is_bound=current.is_bound,
        role=current.role,
        student=serializers.student_out(current.student) if current.student else None,
        staff=StaffOut(
            full_name=current.staff.full_name,
            department=current.staff.department,
            role=current.staff.role,
            position=current.staff.position,
        )
        if current.staff
        else None,
        features={
            "assistant": settings.llm_enabled,
            "bot": settings.bot_enabled,
        },
    )


@router.post("/binding/claim", response_model=MeOut, summary="Привязать студенческий по коду")
async def claim_binding(body: BindRequest, current: CurrentUserDep, session: SessionDep) -> MeOut:
    if current.is_bound:
        return await get_me(current)

    uid = current.app_user.max_user_id
    now = time.monotonic()
    _attempts[uid] = [t for t in _attempts[uid] if now - t < _WINDOW]
    if len(_attempts[uid]) >= _MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED", "message": "Слишком много попыток. Попробуйте через час."},
        )
    _attempts[uid].append(now)

    code = body.code.strip().upper().replace(" ", "")
    res = await session.execute(select(BindingCode).where(BindingCode.code == code))
    bc = res.scalar_one_or_none()

    if bc is None or bc.used_at is not None or bc.expires_at < utcnow():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "BAD_CODE", "message": "Код не найден или уже использован"},
        )

    exists = await session.execute(select(Binding).where(Binding.student_id == bc.student_id))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ALREADY_BOUND", "message": "Этот студент уже привязан"},
        )

    session.add(Binding(app_user_id=current.app_user.id, student_id=bc.student_id))
    bc.used_at = utcnow()
    await session.flush()

    _attempts.pop(uid, None)
    # Именно session.get(Student, ...), а не через bc.student: обращение к ленивой
    # связи в async-контексте поднимает MissingGreenlet.
    current.student = await session.get(Student, bc.student_id)
    log.info("Привязан студент %s к пользователю %s", bc.student_id, uid)
    return await get_me(current)


@router.post("/binding/staff", response_model=MeOut, summary="Активировать роль сотрудника")
async def claim_staff(body: BindRequest, current: CurrentUserDep, session: SessionDep) -> MeOut:
    """Служебный вход для деканата.

    Демонстрационный механизм: коды сотрудников заданы в сиде. В реальном
    внедрении роль приезжает из кадровой системы вуза.
    """
    from app.db.models import Staff
    from app.seed import STAFF_CODES

    if current.staff is not None:
        return await get_me(current)

    entry = STAFF_CODES.get(body.code.strip().upper())
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "BAD_CODE", "message": "Код сотрудника не распознан"},
        )

    full_name, department, role, position = entry
    staff = Staff(
        app_user_id=current.app_user.id,
        full_name=full_name,
        department=department,
        role=role,
        position=position,
    )
    session.add(staff)
    await session.flush()
    current.staff = staff
    log.info("Активирована роль %s для пользователя %s", role, current.app_user.max_user_id)
    return await get_me(current)


@router.post("/uploads", summary="Загрузить файл для поля формы")
async def upload(file: UploadFile, current: BoundUserDep) -> dict:
    allowed = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".webp"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "BAD_FILE_TYPE", "message": "Допустимы PDF и изображения"},
        )

    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "FILE_TOO_LARGE", "message": "Файл больше 10 МБ"},
        )

    stored = f"{current.student.id}_{uuid_lib.uuid4().hex[:12]}{suffix}"
    (settings.uploads_dir / stored).write_bytes(data)
    return {"file": stored, "original_name": file.filename, "size": len(data)}


@router.get("/home", response_model=HomeOut, summary="Данные главного экрана")
async def home(current: BoundUserDep, session: SessionDep) -> HomeOut:
    student = current.student
    now = utcnow()

    # Активные заявки. selectinload обязателен: сериализатор читает events и document,
    # а ленивая загрузка в async-контексте поднимает MissingGreenlet.
    res = await session.execute(
        select(Request)
        .where(Request.student_id == student.id, Request.status.in_(ACTIVE_STATUSES))
        .options(selectinload(Request.events), selectinload(Request.document))
        .order_by(Request.created_at.desc())
        .limit(5)
    )
    active = [serializers.request_out(r) for r in res.scalars().unique()]

    # Ближайшие события под аудиторию
    res = await session.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.starts_at >= now,
            CalendarEvent.starts_at <= now + timedelta(days=30),
            CalendarEvent.status == "PUBLISHED",
        )
        .order_by(CalendarEvent.starts_at)
        .limit(30)
    )
    events = [e for e in res.scalars() if audience_matches(e.audience_json or {}, student)][:5]

    taken_map: dict[int, int] = {}
    my_reg: dict[int, str] = {}
    if events:
        ids = [e.id for e in events]
        res = await session.execute(
            select(EventRegistration.event_id, func.count(EventRegistration.id))
            .where(
                EventRegistration.event_id.in_(ids),
                EventRegistration.status == REG_REGISTERED,
            )
            .group_by(EventRegistration.event_id)
        )
        taken_map = {row[0]: row[1] for row in res.all()}
        res = await session.execute(
            select(EventRegistration).where(
                EventRegistration.event_id.in_(ids),
                EventRegistration.student_id == student.id,
            )
        )
        my_reg = {r.event_id: r.status for r in res.scalars()}

    events_out = [
        serializers.event_out(e, taken_map.get(e.id, 0), my_reg.get(e.id)) for e in events
    ]

    # Рекомендованные возможности
    res = await session.execute(
        select(Opportunity).where(Opportunity.moderation_status == MOD_APPROVED).limit(50)
    )
    opps = list(res.scalars())
    res = await session.execute(
        select(OpportunityInterest).where(OpportunityInterest.student_id == student.id)
    )
    interests = {i.opportunity_id: i.level for i in res.scalars()}

    scored = sorted(
        ((o, score_opportunity(o, student)) for o in opps), key=lambda p: p[1], reverse=True
    )[:5]
    recommended = [
        serializers.opportunity_out(o, interests.get(o.id), sc) for o, sc in scored
    ]

    # Размер колоды
    res = await session.execute(
        select(func.count(Intent.id))
        .where(
            Intent.active.is_(True),
            Intent.author_user_id != current.app_user.id,
            ~Intent.id.in_(
                select(Swipe.intent_id).where(Swipe.actor_user_id == current.app_user.id)
            ),
        )
    )
    deck_size = res.scalar() or 0

    res = await session.execute(
        select(func.count(MatchPair.id)).where(
            (MatchPair.a_user_id == current.app_user.id)
            | (MatchPair.b_user_id == current.app_user.id)
        )
    )
    matches = res.scalar() or 0

    hour = now.hour
    if 5 <= hour < 12:
        greet = "Доброе утро"
    elif 12 <= hour < 18:
        greet = "Добрый день"
    elif 18 <= hour < 23:
        greet = "Добрый вечер"
    else:
        greet = "Доброй ночи"

    return HomeOut(
        greeting=f"{greet}, {student.first_name}",
        active_requests=active,
        upcoming_events=events_out,
        recommended=recommended,
        deck_size=deck_size,
        new_matches=matches,
    )
