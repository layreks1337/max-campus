"""Выдача документа по заявке — общий путь сотрудника и автовыдачи.

Движок (engine.py) знает про шаблоны и переходы, этот модуль — про последствия
выдачи: PDF, запись в аудит, сообщения студенту в чат через outbox.
Кнопка «Выдать документ» у сотрудника и автовыдача типовой справки идут
через одну и ту же функцию issue_document — второго пути к PDF нет.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ST_IN_REVIEW,
    ST_ISSUED,
    ST_READY,
    ST_SIGNING,
    STATUS_TITLES,
    AppUser,
    AuditLog,
    Binding,
    Document,
    Request,
)
from app.modules.notify.service import enqueue
from app.modules.requests import engine, pdf

log = logging.getLogger("requests.service")

# От чьего имени выдаётся типовая справка. Данные — из справочника студентов
# (в демо он синтетический), подписи нет, поэтому «демо» и «автоматическая
# выдача» стоят прямо в имени: так видно и в PDF, и в истории заявки.
AUTO_ISSUER = "Демо-деканат (автоматическая выдача)"

# Шаги автовыдачи — те же статусы, что проходит заявка у сотрудника.
# Машину состояний не обходим: история честно показывает маршрут.
_AUTO_STEPS = (
    (ST_IN_REVIEW, "Типовая справка: данные взяты из справочника студентов"),
    (ST_SIGNING, "Сформирована по шаблону, без подписи сотрудника"),
)


class IssueError(Exception):
    """Документ нельзя выдать из текущего статуса заявки."""


async def student_max_id(session: AsyncSession, req: Request) -> int | None:
    res = await session.execute(
        select(AppUser.max_user_id)
        .join(Binding, Binding.app_user_id == AppUser.id)
        .where(Binding.student_id == req.student_id)
    )
    return res.scalar_one_or_none()


# ── Выдача ────────────────────────────────────────────────────────


async def issue_document(
    session: AsyncSession,
    req: Request,
    *,
    issuer: str,
    actor_kind: str = "staff",
    automatic: bool = False,
) -> Document | None:
    """«На подписи» → «Готова» → PDF → «Выдана» + запись в аудит.

    Уведомление студенту — отдельно (notify_issued): автовыдача ставит его
    в очередь после сообщения «заявка принята», чтобы в чате был верный порядок.
    """
    if req.status == ST_SIGNING:
        await engine.transition(
            session,
            req,
            ST_READY,
            actor_name=issuer,
            actor_kind=actor_kind,
            comment="Документ сформирован" if automatic else "Подписано",
        )
    if req.status != ST_READY:
        raise IssueError(
            f"Выдать можно только из статуса «Готова», сейчас "
            f"«{STATUS_TITLES.get(req.status, req.status)}»"
        )

    document = None
    if req.template.produces_document:
        document = pdf.make_document_record(req, issuer, automatic=automatic)
        session.add(document)
        await session.flush()

    await engine.transition(
        session,
        req,
        ST_ISSUED,
        actor_name=issuer,
        actor_kind=actor_kind,
        comment="Документ выдан автоматически" if automatic else "Документ выдан",
    )
    session.add(
        AuditLog(
            actor_name=issuer,
            action="request.issue",
            entity_type="request",
            entity_id=req.public_no,
            details_json={
                "document_uuid": document.uuid if document else None,
                "automatic": automatic,
            },
        )
    )
    await session.flush()

    # Документ создан в этой же сессии — связь на объекте req ещё помнит старое
    # значение (None). Обновляем её явно, иначе фронт не увидит выданный файл.
    await session.refresh(req, attribute_names=["document", "events"])
    return document


async def auto_issue(session: AsyncSession, req: Request) -> Document | None:
    """Провести типовую заявку по всем шагам в этом же запросе и выдать PDF.

    Всё — в точке сохранения (SAVEPOINT): если сломалось формирование PDF,
    откатываются только шаги автовыдачи, а заявка остаётся «Отправлена»
    и идёт в очередь сотрудника, как нетиповая. Студент ошибки не видит.
    """
    public_no = req.public_no  # после отката точки сохранения поля объекта «протухают»
    try:
        async with session.begin_nested():
            for to_status, comment in _AUTO_STEPS:
                await engine.transition(
                    session,
                    req,
                    to_status,
                    actor_name=AUTO_ISSUER,
                    actor_kind="system",
                    comment=comment,
                )
            document = await issue_document(
                session, req, issuer=AUTO_ISSUER, actor_kind="system", automatic=True
            )
    except Exception:
        log.exception("Автовыдача заявки %s не удалась — заявка уходит сотруднику", public_no)
        # Откат точки сохранения «протухает» изменённые объекты; перечитываем,
        # иначе обращение к полям в async-контексте упадёт на ленивой загрузке.
        await session.refresh(req)
        return None
    log.info("Заявка %s выдана автоматически", public_no)
    return document


# ── Сообщения студенту ────────────────────────────────────────────


async def notify_submitted(
    session: AsyncSession, req: Request, *, max_user_id: int, automatic: bool
) -> None:
    tpl = req.template
    head = f"{tpl.icon} {tpl.short_title or tpl.title} · №{req.public_no}\n\n"
    if automatic:
        body = (
            "Заявка типовая — документ выдан автоматически по данным деканата.\n"
            "PDF придёт следующим сообщением."
        )
    else:
        body = (
            f"Заявка принята. Ориентировочный срок — "
            f"{max(1, round((tpl.sla_hours or 72) / 24))} дн.\n"
            "Сообщу, когда статус изменится."
        )
    await enqueue(
        session,
        max_user_id=max_user_id,
        kind="REQUEST_STATUS",
        text=head + body,
        dedup_key=f"req:{req.id}:SUBMITTED",
        open_app_label="Открыть заявку",
        open_app_payload=f"req_{req.public_no}",
    )


async def notify_issued(
    session: AsyncSession,
    req: Request,
    document: Document | None,
    *,
    max_user_id: int | None = None,
) -> None:
    """PDF файлом в чат; без документа — обычное сообщение о статусе."""
    student_user = max_user_id or await student_max_id(session, req)
    if not student_user:
        return
    if document:
        await enqueue(
            session,
            max_user_id=student_user,
            kind="DOCUMENT_ISSUED",
            text=(
                f"✅ {req.template.short_title or req.template.title} готова\n\n"
                f"№{req.public_no}\n"
                "Подлинность проверяется по QR-коду в документе."
            ),
            dedup_key=f"req:{req.id}:ISSUED:file",
            file_path=document.file_path,
        )
    else:
        await enqueue(
            session,
            max_user_id=student_user,
            kind="REQUEST_STATUS",
            text=engine.status_notification_text(req),
            dedup_key=f"req:{req.id}:ISSUED",
            open_app_label="Открыть заявку",
            open_app_payload=f"req_{req.public_no}",
        )
