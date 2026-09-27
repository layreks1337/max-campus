"""Движок заявок: валидация по JSON-шаблону и машина состояний.

Новый тип справки добавляется строкой в request_template — код не меняется.
"""

from __future__ import annotations

import logging
import random
import string
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ALLOWED_TRANSITIONS,
    ST_ISSUED,
    ST_NEEDS_INFO,
    ST_READY,
    ST_SUBMITTED,
    STATUS_TITLES,
    Request,
    RequestEvent,
    RequestTemplate,
    Student,
    utcnow,
)

log = logging.getLogger("requests.engine")


class ValidationFailed(Exception):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("Проверьте заполнение формы")


class TransitionError(Exception):
    pass


# ── Валидация payload по schema_json ──────────────────────────────


def validate_payload(fields: list[dict], payload: dict[str, Any]) -> dict[str, Any]:
    """Проверяет данные формы против описания полей шаблона.

    Явный валидатор, а не динамический pydantic: проще отлаживать и легко
    добавлять свои правила (размер файла, длина, диапазон).
    """
    errors: dict[str, str] = {}
    clean: dict[str, Any] = {}

    for f in fields:
        name = f.get("name")
        if not name:
            continue
        ftype = f.get("type", "text")
        required = bool(f.get("required"))
        value = payload.get(name)

        is_empty = value is None or value == "" or value == []
        if is_empty:
            if required:
                errors[name] = "Обязательное поле"
            else:
                clean[name] = f.get("default")
            continue

        try:
            clean[name] = _coerce(ftype, value, f)
        except _FieldError as exc:
            errors[name] = str(exc)

    if errors:
        raise ValidationFailed(errors)
    return clean


class _FieldError(Exception):
    pass


def _coerce(ftype: str, value: Any, f: dict) -> Any:
    if ftype == "select":
        if value not in f.get("options", []):
            raise _FieldError("Выберите значение из списка")
        return value

    if ftype == "multiselect":
        if not isinstance(value, list):
            raise _FieldError("Ожидается список")
        bad = [v for v in value if v not in f.get("options", [])]
        if bad:
            raise _FieldError("Недопустимые значения")
        return value

    if ftype == "number":
        try:
            num = int(value)
        except (TypeError, ValueError) as exc:
            raise _FieldError("Ожидается число") from exc
        lo, hi = f.get("min"), f.get("max")
        if lo is not None and num < lo:
            raise _FieldError(f"Минимум {lo}")
        if hi is not None and num > hi:
            raise _FieldError(f"Максимум {hi}")
        return num

    if ftype == "bool":
        return bool(value)

    if ftype == "date":
        s = str(value)
        if len(s) < 8:
            raise _FieldError("Некорректная дата")
        return s

    if ftype == "file":
        # значение — имя файла, положенного через /api/uploads
        s = str(value)
        if not s:
            raise _FieldError("Приложите файл")
        return s

    # text / textarea
    s = str(value).strip()
    max_len = f.get("maxLength", 2000)
    if len(s) > max_len:
        raise _FieldError(f"Не длиннее {max_len} символов")
    min_len = f.get("minLength")
    if min_len and len(s) < min_len:
        raise _FieldError(f"Не короче {min_len} символов")
    return s


# ── Номер заявки ──────────────────────────────────────────────────


async def next_public_no(session: AsyncSession) -> str:
    year = utcnow().year
    res = await session.execute(select(func.count(Request.id)))
    seq = (res.scalar() or 0) + 1
    suffix = "".join(random.choices(string.digits, k=2))
    return f"{year}-{seq:04d}{suffix}"


# ── Создание заявки ───────────────────────────────────────────────


async def create_request(
    session: AsyncSession,
    *,
    template: RequestTemplate,
    student: Student,
    payload: dict[str, Any],
) -> Request:
    clean = validate_payload(template.fields, payload)

    req = Request(
        public_no=await next_public_no(session),
        template_key=template.key,
        student_id=student.id,
        payload_json=clean,
        status=ST_SUBMITTED,
        due_at=utcnow() + timedelta(hours=template.sla_hours or 72),
    )
    session.add(req)
    await session.flush()

    session.add(
        RequestEvent(
            request_id=req.id,
            from_status="",
            to_status=ST_SUBMITTED,
            actor_name=student.short_name,
            actor_kind="student",
            comment="Заявка отправлена",
        )
    )
    await session.flush()
    return req


# ── Переходы ──────────────────────────────────────────────────────


async def transition(
    session: AsyncSession,
    req: Request,
    to_status: str,
    *,
    actor_name: str,
    actor_kind: str = "staff",
    comment: str = "",
) -> Request:
    allowed = ALLOWED_TRANSITIONS.get(req.status, ())
    if to_status not in allowed:
        raise TransitionError(
            f"Из «{STATUS_TITLES.get(req.status, req.status)}» нельзя перейти "
            f"в «{STATUS_TITLES.get(to_status, to_status)}»"
        )

    from_status = req.status
    req.status = to_status
    req.updated_at = utcnow()
    if comment:
        req.comment = comment

    session.add(
        RequestEvent(
            request_id=req.id,
            from_status=from_status,
            to_status=to_status,
            actor_name=actor_name,
            actor_kind=actor_kind,
            comment=comment,
        )
    )
    await session.flush()
    return req


# ── Автовыдача типовых документов ─────────────────────────────────


def can_auto_issue(template: RequestTemplate, payload: dict[str, Any]) -> bool:
    """Типовая ли заявка: шаблон разрешает автовыдачу, и не заполнено ни одно
    поле с флагом manual_review (особая формулировка, бумажный оригинал).

    Решает шаблон, а не код: флаги лежат в той же строке request_template.
    """
    if not template.auto_issue or not template.produces_document:
        return False
    for f in template.fields:
        if not f.get("manual_review"):
            continue
        value = payload.get(f.get("name", ""))
        if value not in (None, "", [], False) and value != f.get("default"):
            return False
    return True


# ── Тексты уведомлений ────────────────────────────────────────────

_STATUS_MESSAGES = {
    "IN_REVIEW": "Заявку приняли в работу.",
    "SIGNING": "Документ передан на подпись.",
    "READY": "Документ готов.",
    "NEEDS_INFO": "Нужно уточнение по заявке.",
    "REJECTED": "Заявка отклонена.",
    "CANCELLED": "Заявка отменена.",
    ST_ISSUED: "Документ выдан.",
}


def status_notification_text(req: Request) -> str:
    title = req.template.short_title or req.template.title
    head = f"{req.template.icon} {title} · №{req.public_no}"
    body = _STATUS_MESSAGES.get(req.status, "")
    status_line = f"Статус: {STATUS_TITLES.get(req.status, req.status)}"

    parts = [head, "", status_line]
    if body:
        parts.append(body)
    if req.status == ST_NEEDS_INFO and req.comment:
        parts.append(f"\nЧто нужно: {req.comment}")
    if req.status == ST_READY:
        parts.append("\nПришлём файлом, как только выдадут.")
    return "\n".join(parts)
