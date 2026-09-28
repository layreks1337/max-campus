"""Наполнение базы демонстрационными данными.

Идемпотентно: повторный запуск ничего не дублирует, поэтому вызывается
при каждом старте приложения. Это упрощает воспроизводимый запуск через Docker —
поднял compose и сразу есть рабочее приложение с данными.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    AppUser,
    Binding,
    BindingCode,
    Building,
    CalendarEvent,
    GradeItem,
    GroupHead,
    GroupPoll,
    Intent,
    KbDocument,
    MatchProfile,
    Opportunity,
    PollVote,
    RequestTemplate,
    ScheduleSlot,
    Student,
    utcnow,
)
from app.seed import campus, demo, knowledge, templates

log = logging.getLogger("seed")

# Код сотрудника -> (ФИО, подразделение, роль, должность)
STAFF_CODES: dict[str, tuple[str, str, str, str]] = {
    code: (name, dept, role, position) for name, dept, role, position, code in demo.STAFF
}

# Срок жизни демо-объявлений «Людей». Считается от последнего продления,
# а продлеваются они при каждом старте и раз в сутки планировщиком.
DEMO_INTENT_TTL_DAYS = 30


async def seed_templates(session: AsyncSession) -> int:
    """Шаблоны обновляем всегда — это конфигурация, а не пользовательские данные."""
    created = 0
    for item in templates.TEMPLATES:
        tpl = await session.get(RequestTemplate, item["key"])
        if tpl is None:
            tpl = RequestTemplate(key=item["key"])
            session.add(tpl)
            created += 1
        # Флаг, убранный из шаблона, должен сняться и в базе, а не остаться прежним
        for field, value in {"auto_issue": False, **item}.items():
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
        return await _refresh_demo(session, CalendarEvent, demo.events(), ("starts_at", "ends_at"))

    items = demo.events()
    for item in items:
        session.add(CalendarEvent(**item, status="PUBLISHED"))
    await session.flush()
    return len(items)


async def seed_opportunities(session: AsyncSession) -> int:
    res = await session.execute(select(func.count(Opportunity.id)))
    if (res.scalar() or 0) > 0:
        return await _refresh_demo(
            session, Opportunity, demo.opportunities(), ("registration_deadline", "starts_at")
        )

    items = demo.opportunities()
    for item in items:
        session.add(Opportunity(**item, moderation_status="APPROVED"))
    await session.flush()
    return len(items)

async def _refresh_demo(session: AsyncSession, model, items: list[dict], date_fields: tuple) -> int:
    """Сдвигает даты демо-записей от текущего дня и обновляет обложки.

    Даты в демо заданы как «через N дней». Посчитанные один раз при первом
    запуске, они за неделю уезжали в прошлое, и к периоду проверки афиша
    оказывалась почти пустой. Записи ищутся по заголовку; добавленные
    пользователями не трогаются. Записи на события сохраняются — меняется
    только дата, не идентификатор.
    """
    by_title = {i["title"]: i for i in items}
    rows = (await session.execute(select(model).where(model.title.in_(by_title)))).scalars()
    n = 0
    for row in rows:
        item = by_title[row.title]
        for field in (*date_fields, "cover_url", "details_json"):
            if field in item:
                setattr(row, field, item[field])
        n += 1
    await session.flush()
    return n


async def seed_demo_people(session: AsyncSession) -> int:
    """Демо-пользователи с привязкой, профилями и объявлениями.

    Нужны, чтобы колода свайпов и buddy-матчинг не были пустыми на демонстрации.
    max_user_id у них отрицательные — так они гарантированно не пересекутся
    с настоящими аккаунтами MAX.
    """
    res = await session.execute(select(func.count(Intent.id)))
    if (res.scalar() or 0) > 0:
        return await extend_demo_intents(session)

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
                expires_at=utcnow() + timedelta(days=DEMO_INTENT_TTL_DAYS),
            )
        )
        created += 1

    await session.flush()
    return created


async def extend_demo_intents(session: AsyncSession) -> int:
    """Продлевает объявления демо-авторов (max_user_id < 0) ещё на 30 дней.

    Раньше срок ставился один раз при первом сиде: объявления, созданные 23.09,
    истекли бы 23.10, и к финалу колода «Людей» оказалась бы пустой. Уже снятые
    по сроку (`expire_intents`) включаются обратно: снять демо-объявление иначе
    некому — войти под отрицательным id нельзя. Объявления живых пользователей
    и демо-копий экспертов (у них id MAX положительные) не трогаются.
    """
    demo_authors = select(AppUser.id).where(AppUser.max_user_id < 0)
    res = await session.execute(
        update(Intent)
        .where(Intent.author_user_id.in_(demo_authors))
        .values(expires_at=utcnow() + timedelta(days=DEMO_INTENT_TTL_DAYS), active=True)
        .execution_options(synchronize_session=False)
    )
    await session.flush()
    return res.rowcount or 0


async def refresh_demo_dates(session: AsyncSession) -> dict[str, int]:
    """Всё, что в демо-данных отсчитывается от «сегодня»: даты событий
    и возможностей (решение 038) и срок демо-объявлений. Идемпотентно —
    повторный вызов в тот же день ничего не меняет по смыслу."""
    return {
        "events": await _refresh_demo(
            session, CalendarEvent, demo.events(), ("starts_at", "ends_at")
        ),
        "opportunities": await _refresh_demo(
            session, Opportunity, demo.opportunities(), ("registration_deadline", "starts_at")
        ),
        "intents": await extend_demo_intents(session),
    }


async def seed_campus(session: AsyncSession) -> int:
    """Расписание, баллы, корпуса и староста — каждое, только если таблица пуста.

    Исключение — обложки корпусов: они обновляются и в заполненной базе, как
    у событий, иначе там остались бы ссылки на удалённые снимки.
    """
    created = 0

    buildings = {b.code: b for b in (await session.execute(select(Building))).scalars()}
    if not buildings:
        for b in campus.BUILDINGS:
            session.add(Building(**b))
            created += 1
    for b in campus.BUILDINGS:
        if b["code"] in buildings:
            buildings[b["code"]].cover_url = b["cover_url"]

    students = list((await session.execute(select(Student))).scalars())

    if not (await session.execute(select(func.count(ScheduleSlot.id)))).scalar():
        groups = {(s.group_name, s.faculty) for s in students}
        for group_name, faculty in sorted(groups):
            for slot in campus.schedule_for(group_name, faculty):
                session.add(ScheduleSlot(**slot))
                created += 1

    if not (await session.execute(select(func.count(GradeItem.id)))).scalar():
        now = utcnow()
        for st in students:
            for i, g in enumerate(campus.grades_for(st.record_book_no, st.faculty)):
                session.add(GradeItem(student_id=st.id, graded_at=now - timedelta(days=1 + i % 9), **g))
                created += 1

    if not (await session.execute(select(func.count(GroupHead.id)))).scalar():
        head = next((s for s in students if s.record_book_no == campus.GROUP_HEAD_RECORD_BOOK), None)
        if head:
            session.add(GroupHead(student_id=head.id, group_name=head.group_name))
            await session.flush()
            # Один опрос уже есть, с голосом одногруппницы — чтобы экран не был пустым
            poll = GroupPoll(
                group_name=head.group_name,
                author_student_id=head.id,
                question="Когда удобнее отработка по матанализу?",
                options=["Суббота, 10:00", "Среда после пар", "Онлайн"],
                closes_at=utcnow() + timedelta(days=5),
            )
            session.add(poll)
            await session.flush()
            mates = [s for s in students if s.group_name == head.group_name and s.id != head.id]
            for i, mate in enumerate(mates):
                session.add(PollVote(poll_id=poll.id, student_id=mate.id, option_idx=i % 3))
            created += 1

    await session.flush()
    return created


async def run_seed(session: AsyncSession) -> dict[str, int]:
    """Полный проход. Возвращает счётчики созданного.

    Шаблоны заявок — конфигурация, обновляются всегда. Остальное — демо-наполнение:
    в пустую таблицу сид кладёт синтетику, а в базу вуза подложил бы учебные баллы
    и расписание его настоящим студентам. Поэтому при SEED_DEMO_DATA=false создаются
    только шаблоны — студентов, коды и регламенты вуз загружает сам (docs/05-rollout.md).
    """
    stats = {"templates": await seed_templates(session)}
    if settings.SEED_DEMO_DATA:
        stats |= {
            "students": await seed_students(session),
            "codes": await seed_binding_codes(session),
            "knowledge": await seed_knowledge(session),
            "events": await seed_events(session),
            "opportunities": await seed_opportunities(session),
            "intents": await seed_demo_people(session),
            "campus": await seed_campus(session),
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
