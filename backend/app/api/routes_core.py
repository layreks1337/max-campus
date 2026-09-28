"""Профиль, привязка студенческого, загрузка файлов, главный экран."""

from __future__ import annotations

import logging
import shutil
import uuid as uuid_lib
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request as HttpRequest, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api import serializers
from app.api.schemas import (
    BindRequest,
    HomeOut,
    MeOut,
    StaffOut,
)
from app.core.config import settings
from app.core.dates import local
from app.core.deps import BoundUserDep, CurrentUser, CurrentUserDep, SessionDep
from app.core.limits import SlidingWindow, client_ip
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
from app.modules.demo import service as demo
from app.modules.feed.scoring import score_opportunity
from app.modules.match.service import audience_matches

log = logging.getLogger("api.core")
router = APIRouter(tags=["core"])

# Ограничение попыток ввода кода: 5 в час на аккаунт. Тестовые id dev-входа
# придумываются без счёта, поэтому ещё и 20 неудачных попыток в час с одного
# адреса — перебор с одной машины упирается в них, а не в число аккаунтов.
_attempts = SlidingWindow(5, 3600)
_failed_by_ip = SlidingWindow(20, 3600)

_RATE_LIMITED = HTTPException(
    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    detail={"code": "RATE_LIMITED", "message": "Слишком много попыток. Попробуйте через час."},
)


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
            "demo": settings.DEMO_MODE,
        },
        tz_offset_hours=settings.UNIVERSITY_TZ_HOURS,
    )


@router.post("/binding/claim", response_model=MeOut, summary="Привязать студенческий по коду")
async def claim_binding(
    body: BindRequest, request: HttpRequest, current: CurrentUserDep, session: SessionDep
) -> MeOut:
    if current.is_bound:
        return await get_me(current)

    uid = current.app_user.max_user_id
    ip = client_ip(request)
    if (ip is not None and not _failed_by_ip.allowed(ip)) or not _attempts.take(uid):
        raise _RATE_LIMITED

    code = body.code.strip().upper().replace(" ", "")
    res = await session.execute(select(BindingCode).where(BindingCode.code == code))
    bc = res.scalar_one_or_none()

    if bc is None or bc.used_at is not None or bc.expires_at < utcnow():
        if ip is not None:
            _failed_by_ip.hit(ip)
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

    _attempts.forget(uid)
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
    from app.seed import STAFF_CODES

    if current.staff is not None:
        return await get_me(current)

    entry = STAFF_CODES.get(body.code.strip().upper())
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "BAD_CODE", "message": "Код сотрудника не распознан"},
        )
    return await _grant_staff(current, session, entry)


async def _grant_staff(
    current: CurrentUser, session: AsyncSession, entry: tuple[str, str, str, str]
) -> MeOut:
    from app.db.models import Staff

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


# ── Демо-вход для экспертов (решение 055) ─────────────────────────


def _require_demo_mode() -> None:
    if not settings.DEMO_MODE:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEMO_DISABLED", "message": "Демо-вход на этом сервере выключен"},
        )


@router.post("/binding/demo", response_model=MeOut, summary="Демо-вход: своя копия демо-студента")
async def claim_demo(request: HttpRequest, current: CurrentUserDep, session: SessionDep) -> MeOut:
    """Вход без кода привязки: аккаунт получает свою копию демо-студента.

    Копия одна на аккаунт и не кончается: уже привязанный аккаунт (копией или
    кодом) просто получает свой профиль. ФИО — из профиля MAX, остальное —
    синтетика шаблона. Работает при DEMO_MODE=true.
    """
    _require_demo_mode()
    if current.is_bound:
        return await get_me(current)

    if not demo.take_slot(current.app_user.max_user_id, client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMITED",
                "message": "Демо-вход сейчас перегружен. Попробуйте через несколько минут.",
            },
        )

    try:
        # Точка сохранения: двойное нажатие даёт два параллельных запроса,
        # и второй упирается в уникальность зачётки DEMO-<id>
        async with session.begin_nested():
            student = await demo.create_copy(session, current.app_user, current.init.user)
        log.info(
            "Демо-копия %s для пользователя %s",
            student.record_book_no, current.app_user.max_user_id,
        )
    except demo.DemoUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DEMO_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except IntegrityError:
        res = await session.execute(
            select(Student).join(Binding, Binding.student_id == Student.id)
            .where(Binding.app_user_id == current.app_user.id)
        )
        student = res.scalar_one_or_none()
        if student is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "CONFLICT", "message": "Не удалось создать демо-профиль, повторите"},
            ) from None

    current.student = student
    return await get_me(current)


@router.post(
    "/binding/demo-staff", response_model=MeOut, summary="Демо: роль деканата в один тап"
)
async def claim_demo_staff(current: CurrentUserDep, session: SessionDep) -> MeOut:
    """Роль сотрудника, который может выдавать документы (как по коду STAFF-002),
    без ввода кода. Только для аккаунта с демо-копией: эксперт сам проводит свою
    заявку до PDF. Очередь такого сотрудника — только заявки его копии."""
    from app.seed import STAFF_CODES

    _require_demo_mode()
    if current.staff is not None:
        return await get_me(current)
    if not demo.is_demo(current.student):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Роль в один тап — только для демо-профиля. "
                           "Сотрудники входят по служебному коду.",
            },
        )
    return await _grant_staff(current, session, STAFF_CODES[demo.DEMO_STAFF_CODE])


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_UPLOAD_CHUNK = 256 * 1024
# Сколько места на диске оставить свободным всегда: базе, логам и ночной копии
_MIN_FREE_DISK_BYTES = 1024 * 1024 * 1024


def _upload_error(code: str, message: str, http: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(status_code=http, detail={"code": code, "message": message})


def _check_upload_quota(student_id: int) -> None:
    """Квота вложений: на студента, на весь сервер и по свободному месту.

    Файлы вложений не удаляются (на них ссылаются заявки), поэтому без квоты
    скрипт с демо-аккаунтов за вечер забил бы диск стенда вместе с базой.
    """
    folder = settings.uploads_dir
    mine = sum(1 for _ in folder.glob(f"{student_id}_*"))
    if mine >= settings.UPLOADS_PER_STUDENT:
        raise _upload_error(
            "UPLOAD_QUOTA",
            f"Уже загружено {mine} файлов — больше нельзя. Приложите нужный к новой заявке.",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
    total = sum(f.stat().st_size for f in folder.iterdir() if f.is_file())
    free = shutil.disk_usage(folder).free
    if total >= settings.UPLOADS_TOTAL_MB * 1024 * 1024 or free < _MIN_FREE_DISK_BYTES:
        log.warning("Хранилище вложений заполнено: %s МБ, свободно %s МБ",
                    total // 2**20, free // 2**20)
        raise _upload_error(
            "STORAGE_FULL",
            "Хранилище файлов заполнено. Подайте заявку без вложения или попробуйте позже.",
            status.HTTP_507_INSUFFICIENT_STORAGE,
        )


@router.post("/uploads", summary="Загрузить файл для поля формы")
async def upload(file: UploadFile, current: BoundUserDep) -> dict:
    allowed = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".webp"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise _upload_error("BAD_FILE_TYPE", "Допустимы PDF и изображения")
    _check_upload_quota(current.student.id)

    # Кусками и с лимитом: файл целиком в память не читается, а слишком большой
    # не остаётся на диске. Тело запроса и так не больше 11 МБ (main.py).
    stored = f"{current.student.id}_{uuid_lib.uuid4().hex[:12]}{suffix}"
    target = settings.uploads_dir / stored
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(_UPLOAD_CHUNK):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise _upload_error("FILE_TOO_LARGE", "Файл больше 10 МБ")
                out.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"file": stored, "original_name": file.filename, "size": size}


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

    # Час по Иркутску, а не по UTC: иначе утром студент видел «Доброй ночи»
    hour = local(now).hour
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
