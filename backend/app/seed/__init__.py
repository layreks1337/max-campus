"""Наполнение базы демонстрационными данными.

Идемпотентно: повторный запуск ничего не дублирует, поэтому вызывается
при каждом старте приложения. Это упрощает воспроизводимый запуск через Docker —
поднял compose и сразу есть рабочее приложение с данными.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    AppUser,
    Binding,
    BindingCode,
    CalendarEvent,
    Intent,
    KbDocument,
    MatchProfile,
    Opportunity,
    RequestTemplate,
    Student,
    utcnow,
)
from app.seed import demo, knowledge, templates

log = logging.getLogger("seed")

# Код сотрудника -> (ФИО, подразделение, роль, должность)
STAFF_CODES: dict[str, tuple[str, str, str, str]] = {
    code: (name, dept, role, position) for name, dept, role, position, code in demo.STAFF
}


async def seed_templates(session: AsyncSession) -> int:
    """Шаблоны обновляем всегда — это конфигурация, а не пользовательские данные."""
    created = 0
    for item in templates.TEMPLATES:
        tpl = await session.get(RequestTemplate, item["key"])
        if tpl is None:
            tpl = RequestTemplate(key=item["key"])
            session.add(tpl)
            created += 1
        for field, value in item.items():
            if field != "key":
                setattr(tpl, field, value)
    await session.flush()
    return created


async def seed_students(session: AsyncSession) -> int:
    res = await session.execute(select(func.count(Student.id)))
    if (res.scalar() or 0) > 0:
        return 0

    created = 0
    for row in demo.STUDENTS:
        last, first, middle, group, faculty, course, book, birth, form, funding = row
        session.add(
            Student(
                last_name=last,
                first_name=first,
                middle_name=middle,
                group_name=group,
                faculty=faculty,
                course=course,
                record_book_no=book,
                birth_date=birth,
                education_form=form,
                funding=funding,
                enrolled_year=2026 - course + 1,
            )
        )
        created += 1
    await session.flush()
    return created


async def seed_binding_codes(session: AsyncSession) -> int:
    res = await session.execute(select(func.count(BindingCode.code)))
    if (res.scalar() or 0) > 0:
        return 0

    res = await session.execute(select(Student).order_by(Student.id))
    students = list(res.scalars())
    created = 0
    for code, idx in demo.BINDING_CODES:
        if idx >= len(students):
            continue
        session.add(
            BindingCode(
                code=code,
                student_id=students[idx].id,
                expires_at=utcnow() + timedelta(days=365),
            )
        )
        created += 1
    await session.flush()
    return created


async def seed_knowledge(session: AsyncSession) -> int:
    res = await session.execute(select(func.count(KbDocument.id)))
    if (res.scalar() or 0) > 0:
        return 0

    for item in knowledge.DOCUMENTS:
        session.add(
            KbDocument(
                title=item["title"],
                source_type=item["source_type"],
                source_url=item.get("source_url", ""),
                body=item["body"],
                is_demo=True,
            )
        )
    await session.flush()
    return len(knowledge.DOCUMENTS)


async def seed_events(session: AsyncSession) -> int:
    res = await session.execute(select(func.count(CalendarEvent.id)))
    if (res.scalar() or 0) > 0:
        return 0

    items = demo.events()
    for item in items:
        session.add(CalendarEvent(**item, status="PUBLISHED"))
    await session.flush()
    return len(items)


async def seed_opportunities(session: AsyncSession) -> int:
    res = await session.execute(select(func.count(Opportunity.id)))
    if (res.scalar() or 0) > 0:
        return 0

    items = demo.opportunities()
    for item in items:
        session.add(Opportunity(**item, moderation_status="APPROVED"))
    await session.flush()
    return len(items)


async def seed_demo_people(session: AsyncSession) -> int:
    """Демо-пользователи с привязкой, профилями и объявлениями.

    Нужны, чтобы колода свайпов и buddy-матчинг не были пустыми на демонстрации.
    max_user_id у них отрицательные — так они гарантированно не пересекутся
    с настоящими аккаунтами MAX.
    """
    res = await session.execute(select(func.count(Intent.id)))
    if (res.scalar() or 0) > 0:
        return 0

    res = await session.execute(select(Student).order_by(Student.id))
    students = list(res.scalars())
    if not students:
        return 0

    # Первые REAL_USER_SLOTS студентов не трогаем: их коды раздаются живым людям,
    # и если занять этих студентов демо-аккаунтами, привязка на демонстрации
    # упадёт с «Этот студент уже привязан».
    users: list[AppUser | None] = [None] * len(students)
    for i, student in enumerate(students):
        if i < demo.REAL_USER_SLOTS:
            continue

        res = await session.execute(select(AppUser).where(AppUser.max_user_id == -(1000 + i)))
        user = res.scalar_one_or_none()
        if user is None:
            user = AppUser(
                max_user_id=-(1000 + i),
                first_name=student.first_name,
                last_name=student.last_name,
                username=f"demo_{student.record_book_no}",
            )
            session.add(user)
            await session.flush()
        users[i] = user

        res = await session.execute(select(Binding).where(Binding.student_id == student.id))
        if res.scalar_one_or_none() is None:
            session.add(
                Binding(app_user_id=user.id, student_id=student.id, method="demo-seed")
            )
    await session.flush()

    for idx, wants_mentor, wants_mentee, tags, district in demo.MATCH_PROFILES:
        if idx >= len(users) or users[idx] is None:
            continue
        res = await session.execute(
            select(MatchProfile).where(MatchProfile.app_user_id == users[idx].id)
        )
        if res.scalar_one_or_none() is not None:
            continue
        session.add(
            MatchProfile(
                app_user_id=users[idx].id,
                bio="",
                tags=tags,
                district=district,
                wants_mentor=wants_mentor,
                wants_mentee=wants_mentee,
            )
        )

    created = 0
    for author_idx, kind, title, description, tags in demo.INTENTS:
        if author_idx >= len(users) or users[author_idx] is None:
            continue
        session.add(
            Intent(
                author_user_id=users[author_idx].id,
                kind=kind,
                title=title,
                description=description,
                tags=tags,
                expires_at=utcnow() + timedelta(days=30),
            )
        )
        created += 1

    await session.flush()
    return created


async def run_seed(session: AsyncSession) -> dict[str, int]:
    """Полный проход. Возвращает счётчики созданного."""
    stats = {
        "templates": await seed_templates(session),
        "students": await seed_students(session),
        "codes": await seed_binding_codes(session),
        "knowledge": await seed_knowledge(session),
        "events": await seed_events(session),
        "opportunities": await seed_opportunities(session),
        "intents": await seed_demo_people(session),
    }
    await session.commit()

    if any(stats.values()):
        log.info("Сид выполнен: %s", stats)
    return stats


async def index_knowledge_if_needed(session: AsyncSession) -> int:
    """Считает эмбеддинги для документов, у которых их ещё нет."""
    from app.db.models import KbChunk
    from app.modules.assistant.rag import index_document

    if not settings.llm_enabled:
        log.info("LLM не настроен — индексация базы знаний пропущена")
        return 0

    res = await session.execute(select(func.count(KbChunk.id)))
    if (res.scalar() or 0) > 0:
        return 0

    res = await session.execute(select(KbDocument).where(KbDocument.active.is_(True)))
    docs = list(res.scalars())
    total = 0
    for doc in docs:
        try:
            total += await index_document(session, doc)
        except Exception:
            log.exception("Не удалось проиндексировать «%s»", doc.title)
    await session.commit()
    log.info("Проиндексировано чанков базы знаний: %s", total)
    return total
