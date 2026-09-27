"""Зависимости FastAPI: аутентификация, текущий студент, роли."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import (
    InitData,
    InitDataError,
    parse_dev_auth,
    validate_init_data,
    validate_link_token,
)
from app.db.models import STAFF_ROLES, AppUser, Binding, Staff, Student, utcnow
from app.db.session import get_session

# Кеш результатов валидации: HMAC на каждый запрос списка — расточительно
_init_cache: dict[str, tuple[float, InitData]] = {}
_CACHE_TTL = 300.0

# Внутренняя метка токена из ссылки бота (заголовок `Authorization: MaxLink <токен>`)
_LINK_PREFIX = "link:"


def _cached_validate(raw: str) -> InitData:
    # Ссылка бота проверяется без кеша: HMAC дешёвый, а кеш на 5 минут
    # продлил бы жизнь уже истёкшему токену
    if raw.startswith(_LINK_PREFIX):
        return validate_link_token(raw[len(_LINK_PREFIX) :])

    now = time.monotonic()
    hit = _init_cache.get(raw)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    if raw.startswith("dev:"):
        data = parse_dev_auth(raw)
    else:
        data = validate_init_data(raw)

    if len(_init_cache) > 512:
        _init_cache.clear()
    _init_cache[raw] = (now, data)
    return data


def _extract_raw(authorization: str | None, x_init_data: str | None) -> str:
    if x_init_data:
        return x_init_data
    if authorization:
        if authorization.startswith("MaxInitData "):
            return authorization[len("MaxInitData ") :]
        if authorization.startswith("MaxLink "):
            return _LINK_PREFIX + authorization[len("MaxLink ") :]
        return authorization
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "NO_AUTH", "message": "Нет заголовка авторизации"},
    )


async def get_init_data(
    authorization: Annotated[str | None, Header()] = None,
    x_init_data: Annotated[str | None, Header(alias="X-Init-Data")] = None,
) -> InitData:
    raw = _extract_raw(authorization, x_init_data)
    try:
        return _cached_validate(raw)
    except InitDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "BAD_INIT_DATA", "message": str(exc)},
        ) from exc


async def get_app_user(
    init: Annotated[InitData, Depends(get_init_data)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AppUser:
    """Находит пользователя по max_user_id, создаёт при первом входе."""
    res = await session.execute(
        select(AppUser)
        .where(AppUser.max_user_id == init.user.id)
        .options(selectinload(AppUser.binding), selectinload(AppUser.staff))
    )
    user = res.scalar_one_or_none()

    if user is None:
        user = AppUser(
            max_user_id=init.user.id,
            first_name=init.user.first_name,
            last_name=init.user.last_name,
            username=init.user.username,
            photo_url=init.user.photo_url,
        )
        session.add(user)
        await session.flush()
    else:
        user.last_seen_at = utcnow()
        if init.user.first_name and not user.first_name:
            user.first_name = init.user.first_name

    if not init.user.first_name and not init.user.last_name:
        # Вход по ссылке бота: в токене только id. Имя — из профиля, который бот
        # записал по апдейту MAX, иначе демо-копия получила бы имя шаблона.
        # Объект не кешируется (_cached_validate), дописывать в него безопасно.
        init.user.first_name = user.first_name or ""
        init.user.last_name = user.last_name or ""

    return user


@dataclass
class CurrentUser:
    """Всё, что нужно знать о том, кто сейчас в приложении."""

    app_user: AppUser
    student: Student | None
    staff: Staff | None
    init: InitData

    @property
    def is_bound(self) -> bool:
        return self.student is not None

    @property
    def role(self) -> str:
        return self.staff.role if self.staff else "STUDENT"

    @property
    def is_staff(self) -> bool:
        return self.staff is not None and self.staff.role in STAFF_ROLES

    @property
    def display_name(self) -> str:
        if self.student:
            return self.student.full_name
        return self.app_user.display_name


async def get_current_user(
    init: Annotated[InitData, Depends(get_init_data)],
    app_user: Annotated[AppUser, Depends(get_app_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CurrentUser:
    student = None
    res = await session.execute(
        select(Student).join(Binding, Binding.student_id == Student.id).where(
            Binding.app_user_id == app_user.id
        )
    )
    student = res.scalar_one_or_none()

    res = await session.execute(select(Staff).where(Staff.app_user_id == app_user.id))
    staff = res.scalar_one_or_none()

    return CurrentUser(app_user=app_user, student=student, staff=staff, init=init)


async def require_binding(
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    """Защищённые эндпоинты требуют привязанного студента."""
    if not current.is_bound:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BINDING_REQUIRED",
                "message": "Сначала привяжите студенческий по коду",
            },
        )
    return current


async def require_staff(
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    if not current.is_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Нужны права сотрудника"},
        )
    return current


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
BoundUserDep = Annotated[CurrentUser, Depends(require_binding)]
StaffUserDep = Annotated[CurrentUser, Depends(require_staff)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
