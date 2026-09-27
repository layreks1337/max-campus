"""Демо-вход для экспертов: личная копия шаблонного студента.

Кодов привязки четыре, и они одноразовые — второй же эксперт получил бы «код уже
использован». Поэтому кнопка «Попробовать как студент (демо)» создаёт каждому
аккаунту MAX свою копию демо-студента: та же группа, баллы и права старосты,
номер зачётки DEMO-<id>, ФИО — из профиля MAX. Данные синтетические (FAQ, п. 13).

Копии живут в группе оригинала — иначе пропали бы расписание, опросы и афиша.
Чтобы эксперты не мешали друг другу и настоящей группе, копии исключены из всего,
что касается группы целиком: рассылок старосты, напоминаний о парах, счётчика
«человек в группе», пула наставников. Решение 055.
"""

from __future__ import annotations

import time
from collections import deque

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import MaxUser
from app.db.models import AppUser, Binding, GradeItem, GroupHead, Student
from app.seed.demo import DEMO_TEMPLATE_RECORD_BOOK

DEMO_PREFIX = "DEMO-"
BINDING_METHOD = "demo-copy"
# Роль деканата в один тап — те же права, что у кода STAFF-002 (может выдавать)
DEMO_STAFF_CODE = "STAFF-002"

# Имена, которые dev-вход подставляет, когда настоящего нет. С ними копия
# называется как шаблон: «Dev User» в справке хуже синтетической Петровой.
_PLACEHOLDER_NAMES = {"dev", "dev user"}

# Моменты создания копий за последний час — на весь процесс
_created: deque[float] = deque()


class DemoUnavailable(Exception):
    """Демо-вход сейчас невозможен: база не наполнена или исчерпан лимит."""


def is_demo(student: Student | None) -> bool:
    return student is not None and student.record_book_no.startswith(DEMO_PREFIX)


def demo_filter():
    """SQL-условие «студент — демо-копия» для запросов, где участвует Student."""
    return Student.record_book_no.like(f"{DEMO_PREFIX}%")


def demo_student_ids():
    """Подзапрос id всех демо-копий — для таблиц, где есть только student_id."""
    return select(Student.id).where(demo_filter())


def take_slot() -> bool:
    """Занять место под новую копию в часовом лимите сервера."""
    now = time.monotonic()
    while _created and now - _created[0] > 3600:
        _created.popleft()
    if len(_created) >= settings.DEMO_COPIES_PER_HOUR:
        return False
    _created.append(now)
    return True


def _profile_name(user: MaxUser) -> tuple[str, str] | None:
    """(имя, фамилия) из профиля MAX или None, если имени нет."""
    first = (user.first_name or "").strip()[:80]
    last = (user.last_name or "").strip()[:80]
    if not first:
        first, last = last, ""
    if not first or first.lower() in _PLACEHOLDER_NAMES:
        return None
    return first, last


async def create_copy(session: AsyncSession, app_user: AppUser, profile: MaxUser) -> Student:
    """Копия шаблонного студента, привязанная к аккаунту. Коммит — на вызывающем."""
    res = await session.execute(
        select(Student).where(Student.record_book_no == DEMO_TEMPLATE_RECORD_BOOK)
    )
    tpl = res.scalar_one_or_none()
    if tpl is None:
        raise DemoUnavailable("Демо-данные ещё не загружены — попробуйте через минуту")

    name = _profile_name(profile)
    if name:
        first, last, middle = name[0], name[1], ""
    else:
        first, last, middle = tpl.first_name, tpl.last_name, tpl.middle_name

    copy = Student(
        last_name=last,
        first_name=first,
        middle_name=middle,
        group_name=tpl.group_name,
        faculty=tpl.faculty,
        course=tpl.course,
        record_book_no=f"{DEMO_PREFIX}{app_user.id}",
        birth_date=tpl.birth_date,
        education_form=tpl.education_form,
        funding=tpl.funding,
        enrolled_year=tpl.enrolled_year,
    )
    session.add(copy)
    await session.flush()

    res = await session.execute(select(GradeItem).where(GradeItem.student_id == tpl.id))
    for g in res.scalars():
        session.add(
            GradeItem(
                student_id=copy.id,
                subject=g.subject,
                title=g.title,
                points=g.points,
                max_points=g.max_points,
                control=g.control,
                teacher=g.teacher,
                graded_at=g.graded_at,
            )
        )

    # Шаблон — староста: эксперт должен увидеть экран опросов группы
    res = await session.execute(select(GroupHead.id).where(GroupHead.student_id == tpl.id))
    if res.first() is not None:
        session.add(GroupHead(student_id=copy.id, group_name=copy.group_name))

    session.add(Binding(app_user_id=app_user.id, student_id=copy.id, method=BINDING_METHOD))
    await session.flush()
    return copy
