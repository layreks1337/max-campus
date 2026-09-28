"""Заявки: шаблоны, подача, трекинг, очередь деканата, выдача документа."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api import serializers
from app.api.schemas import (
    AnswerInfoIn,
    CreateRequestIn,
    RequestOut,
    TemplateOut,
    TransitionIn,
)
from app.core.deps import (
    ISSUER_ROLES,
    REQUEST_ROLES,
    BoundUserDep,
    SessionDep,
    StaffUserDep,
    require_role,
)
from app.db.models import (
    ACTIVE_STATUSES,
    ST_CANCELLED,
    ST_IN_REVIEW,
    ST_ISSUED,
    ST_NEEDS_INFO,
    ST_READY,
    AuditLog,
    Request,
    RequestTemplate,
    utcnow,
)
from app.modules.demo.service import demo_student_ids, is_demo
from app.modules.notify.service import enqueue
from app.modules.requests import engine, service

log = logging.getLogger("api.requests")
router = APIRouter(prefix="/requests", tags=["requests"])
staff_router = APIRouter(prefix="/staff/requests", tags=["staff"])


def _load_full(stmt):
    return stmt.options(
        selectinload(Request.events), selectinload(Request.document)
    )


# ── Шаблоны ───────────────────────────────────────────────────────


@router.get("/templates", response_model=list[TemplateOut], summary="Доступные шаблоны заявок")
async def list_templates(current: BoundUserDep, session: SessionDep) -> list[TemplateOut]:
    res = await session.execute(
        select(RequestTemplate)
        .where(RequestTemplate.active.is_(True))
        .order_by(RequestTemplate.sort_order, RequestTemplate.title)
    )
    return [serializers.template_out(t) for t in res.scalars()]


@router.get("/templates/{key}", response_model=TemplateOut, summary="Схема полей шаблона")
async def get_template(key: str, current: BoundUserDep, session: SessionDep) -> TemplateOut:
    tpl = await session.get(RequestTemplate, key)
    if tpl is None or not tpl.active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Шаблон не найден"},
        )
    return serializers.template_out(tpl)


# ── Студент ───────────────────────────────────────────────────────


@router.get("", response_model=list[RequestOut], summary="Мои заявки")
async def my_requests(
    current: BoundUserDep,
    session: SessionDep,
    only_active: bool = Query(False, description="Только заявки в работе"),
) -> list[RequestOut]:
    stmt = select(Request).where(Request.student_id == current.student.id)
    if only_active:
        stmt = stmt.where(Request.status.in_(ACTIVE_STATUSES))
    stmt = _load_full(stmt.order_by(Request.created_at.desc()))
    res = await session.execute(stmt)
    return [serializers.request_out(r) for r in res.scalars().unique()]


@router.post("", response_model=RequestOut, status_code=201, summary="Подать заявку")
async def create_request(
    body: CreateRequestIn, current: BoundUserDep, session: SessionDep
) -> RequestOut:
    tpl = await session.get(RequestTemplate, body.template_key)
    if tpl is None or not tpl.active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Шаблон не найден"},
        )

    try:
        req = await engine.create_request(
            session, template=tpl, student=current.student, payload=body.payload
        )
    except engine.ValidationFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VALIDATION_FAILED",
                "message": "Проверьте заполнение формы",
                "details": exc.errors,
            },
        ) from exc

    # Типовая справка выдаётся в этом же запросе: статусы → PDF → чат.
    # Нетиповая (или если автовыдача сорвалась) остаётся в очереди сотрудника.
    document = None
    if engine.can_auto_issue(tpl, req.payload_json):
        document = await service.auto_issue(session, req)

    max_user_id = current.app_user.max_user_id
    await service.notify_submitted(
        session, req, max_user_id=max_user_id, automatic=document is not None
    )
    if document is not None:
        await service.notify_issued(session, req, document, max_user_id=max_user_id)

    res = await session.execute(_load_full(select(Request).where(Request.id == req.id)))
    return serializers.request_out(res.scalar_one())


@router.get("/{public_no}", response_model=RequestOut, summary="Заявка и её история")
async def get_request(public_no: str, current: BoundUserDep, session: SessionDep) -> RequestOut:
    res = await session.execute(
        _load_full(select(Request).where(Request.public_no == public_no))
    )
    req = res.unique().scalar_one_or_none()
    if req is None or req.student_id != current.student.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Заявка не найдена"},
        )
    return serializers.request_out(req)


@router.post("/{public_no}/cancel", response_model=RequestOut, summary="Отменить заявку")
async def cancel_request(
    public_no: str, current: BoundUserDep, session: SessionDep
) -> RequestOut:
    res = await session.execute(
        _load_full(select(Request).where(Request.public_no == public_no))
    )
    req = res.unique().scalar_one_or_none()
    if req is None or req.student_id != current.student.id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Не найдена"})

    try:
        await engine.transition(
            session,
            req,
            ST_CANCELLED,
            actor_name=current.student.short_name,
            actor_kind="student",
            comment="Отменена студентом",
        )
    except engine.TransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "BAD_TRANSITION", "message": str(exc)},
        ) from exc
    return serializers.request_out(req)


@router.post("/{public_no}/info", response_model=RequestOut, summary="Ответить на уточнение")
async def answer_info(
    public_no: str, body: AnswerInfoIn, current: BoundUserDep, session: SessionDep
) -> RequestOut:
    res = await session.execute(
        _load_full(select(Request).where(Request.public_no == public_no))
    )
    req = res.unique().scalar_one_or_none()
    if req is None or req.student_id != current.student.id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Не найдена"})
    if req.status != ST_NEEDS_INFO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "BAD_TRANSITION", "message": "Заявка не ждёт уточнений"},
        )

    payload = dict(req.payload_json or {})
    payload["clarification"] = body.comment
    req.payload_json = payload

    await engine.transition(
        session,
        req,
        ST_IN_REVIEW,
        actor_name=current.student.short_name,
        actor_kind="student",
        comment=body.comment,
    )
    return serializers.request_out(req)


# ── Деканат ───────────────────────────────────────────────────────


def _staff_scope(stmt, current):
    """Какие заявки видит сотрудник. Заодно — проверка, что роль работает с заявками.

    Демо-профиль в роли деканата — только заявки своей копии: эксперт сразу
    находит свою заявку. Остальные сотрудники — все заявки, кроме демо-копий.
    Копии названы по профилям MAX, то есть настоящими именами экспертов, а коды
    STAFF-001/002 опубликованы: иначе любой, введя код, читал бы чужие заявки
    с именами и PDF и писал бы экспертам в чат от имени бота.
    """
    require_role(current, REQUEST_ROLES, "Очередь заявок")
    if is_demo(current.student):
        return stmt.where(Request.student_id == current.student.id)
    return stmt.where(Request.student_id.not_in(demo_student_ids()))


@staff_router.get("", response_model=list[RequestOut], summary="Очередь заявок")
async def staff_queue(
    current: StaffUserDep,
    session: SessionDep,
    status_filter: str | None = Query(None, alias="status"),
    overdue: bool = Query(False, description="Только просроченные"),
) -> list[RequestOut]:
    stmt = _staff_scope(select(Request), current)
    if status_filter:
        stmt = stmt.where(Request.status == status_filter)
    else:
        stmt = stmt.where(Request.status.in_(ACTIVE_STATUSES))
    if overdue:
        stmt = stmt.where(Request.due_at.is_not(None), Request.due_at < utcnow())

    stmt = _load_full(stmt.order_by(Request.created_at.asc()).limit(200))
    res = await session.execute(stmt)
    return [serializers.request_out(r, with_student=True) for r in res.scalars().unique()]


@staff_router.post(
    "/{public_no}/transition", response_model=RequestOut, summary="Сменить статус"
)
async def staff_transition(
    public_no: str, body: TransitionIn, current: StaffUserDep, session: SessionDep
) -> RequestOut:
    res = await session.execute(
        _load_full(_staff_scope(select(Request).where(Request.public_no == public_no), current))
    )
    req = res.unique().scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Не найдена"})
    if body.to_status == ST_ISSUED and req.status == ST_READY:
        # Переход допустим, но без PDF: документ формирует только выдача
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "BAD_TRANSITION", "message": "Выдать документ — кнопкой «Выдать документ»"},
        )
    if body.to_status == ST_READY:
        require_role(current, ISSUER_ROLES, "Подписать документ")

    try:
        await engine.transition(
            session,
            req,
            body.to_status,
            actor_name=current.staff.full_name,
            actor_kind="staff",
            comment=body.comment,
        )
    except engine.TransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "BAD_TRANSITION", "message": str(exc)},
        ) from exc

    session.add(
        AuditLog(
            actor_name=current.staff.full_name,
            action="request.transition",
            entity_type="request",
            entity_id=req.public_no,
            details_json={"to": body.to_status, "comment": body.comment},
        )
    )

    student_user = await service.student_max_id(session, req)
    if student_user:
        await enqueue(
            session,
            max_user_id=student_user,
            kind="REQUEST_STATUS",
            text=engine.status_notification_text(req),
            dedup_key=f"req:{req.id}:{req.status}",
            open_app_label="Открыть заявку",
            open_app_payload=f"req_{req.public_no}",
        )
    return serializers.request_out(req, with_student=True)


@staff_router.post("/{public_no}/issue", response_model=RequestOut, summary="Выдать документ")
async def staff_issue(
    public_no: str, current: StaffUserDep, session: SessionDep
) -> RequestOut:
    res = await session.execute(
        _load_full(_staff_scope(select(Request).where(Request.public_no == public_no), current))
    )
    req = res.unique().scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Не найдена"})
    require_role(current, ISSUER_ROLES, "Выдать документ")

    try:
        document = await service.issue_document(session, req, issuer=current.staff.full_name)
    except service.IssueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "BAD_TRANSITION", "message": str(exc)},
        ) from exc
    await service.notify_issued(session, req, document)
    return serializers.request_out(req, with_student=True)
