"""Матчинг: колода интентов, свайпы, взаимные отклики, buddy-автоматч."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AppUser,
    Binding,
    Intent,
    MatchPair,
    MatchProfile,
    Student,
    Swipe,
    utcnow,
)
from app.modules.notify.service import enqueue

log = logging.getLogger("match")


def audience_matches(audience: dict, student: Student) -> bool:
    """Пустой список в фильтре означает «все». Используется и событиями."""
    if not audience:
        return True
    faculties = audience.get("faculties") or []
    if faculties and student.faculty not in faculties:
        return False
    courses = audience.get("courses") or []
    if courses and student.course not in courses:
        return False
    groups = audience.get("groups") or []
    if groups and student.group_name not in groups:
        return False
    if audience.get("only_freshmen") and student.course != 1:
        return False
    return True


def score_intent(
    intent: Intent,
    *,
    viewer: Student,
    author: Student | None,
    viewer_tags: set[str],
    viewer_district: str = "",
) -> float:
    score = 0.0
    score += 3.0 * len(set(intent.tags or []) & viewer_tags)

    if author:
        if author.faculty == viewer.faculty:
            score += 2.0
        if abs(author.course - viewer.course) <= 1:
            score += 1.0
        # наставничество работает наоборот: нужен разрыв в курсах
        if intent.kind in ("MENTEE", "MENTOR") and author.course > viewer.course:
            score += 2.0

    if intent.kind == "COMMUTE" and viewer_district:
        if viewer_district.lower() in (intent.description or "").lower():
            score += 1.0

    age_days = (utcnow() - intent.created_at).days if intent.created_at else 0
    score -= min(age_days / 7.0, 2.0) * 2.0

    return round(score, 2)


async def get_deck(
    session: AsyncSession,
    *,
    app_user_id: int,
    student: Student,
    limit: int = 20,
) -> list[tuple[Intent, Student | None, float]]:
    """Колода: активные чужие интенты, которые ещё не свайпнуты."""
    res = await session.execute(select(MatchProfile).where(MatchProfile.app_user_id == app_user_id))
    profile = res.scalar_one_or_none()
    viewer_tags = set(profile.tags or []) if profile else set()
    district = profile.district if profile else ""

    swiped = select(Swipe.intent_id).where(Swipe.actor_user_id == app_user_id)
    res = await session.execute(
        select(Intent)
        .where(
            Intent.active.is_(True),
            Intent.author_user_id != app_user_id,
            Intent.id.not_in(swiped),
        )
        .order_by(Intent.created_at.desc())
        .limit(120)
    )
    intents = list(res.scalars())
    if not intents:
        return []

    author_ids = {i.author_user_id for i in intents}
    res = await session.execute(
        select(Binding.app_user_id, Student)
        .join(Student, Student.id == Binding.student_id)
        .where(Binding.app_user_id.in_(author_ids))
    )
    authors = {row[0]: row[1] for row in res.all()}

    scored = [
        (
            i,
            authors.get(i.author_user_id),
            score_intent(
                i,
                viewer=student,
                author=authors.get(i.author_user_id),
                viewer_tags=viewer_tags,
                viewer_district=district,
            ),
        )
        for i in intents
    ]
    # свежие и релевантные вперёд; протухшие интенты уходят вниз
    scored.sort(key=lambda t: t[2], reverse=True)
    return scored[:limit]


async def register_swipe(
    session: AsyncSession,
    *,
    app_user_id: int,
    intent_id: int,
    decision: str,
) -> MatchPair | None:
    """Записывает свайп. При взаимности создаёт пару и шлёт пуш обоим."""
    existing = await session.execute(
        select(Swipe).where(Swipe.actor_user_id == app_user_id, Swipe.intent_id == intent_id)
    )
    if existing.scalar_one_or_none() is not None:
        return None

    session.add(Swipe(actor_user_id=app_user_id, intent_id=intent_id, decision=decision))
    await session.flush()

    if decision != "LIKE":
        return None

    intent = await session.get(Intent, intent_id)
    if intent is None:
        return None

    author_id = intent.author_user_id

    # Взаимность: автор интента лайкнул что-то из моих интентов
    my_intents = select(Intent.id).where(Intent.author_user_id == app_user_id)
    res = await session.execute(
        select(Swipe).where(
            Swipe.actor_user_id == author_id,
            Swipe.decision == "LIKE",
            Swipe.intent_id.in_(my_intents),
        )
    )
    reciprocal = res.scalars().first()
    if reciprocal is None:
        return None

    pair = MatchPair(
        a_user_id=min(app_user_id, author_id),
        b_user_id=max(app_user_id, author_id),
        intent_id=intent_id,
        origin="SWIPE",
    )
    session.add(pair)
    await session.flush()

    await _notify_match(session, app_user_id, author_id, intent.title)
    return pair


async def _notify_match(
    session: AsyncSession, user_a: int, user_b: int, about: str
) -> None:
    users = {}
    res = await session.execute(select(AppUser).where(AppUser.id.in_([user_a, user_b])))
    for u in res.scalars():
        users[u.id] = u

    for me, other in ((user_a, user_b), (user_b, user_a)):
        me_user, other_user = users.get(me), users.get(other)
        if not me_user or not other_user:
            continue
        handle = f"@{other_user.username}" if other_user.username else "загляни в приложение"
        await enqueue(
            session,
            max_user_id=me_user.max_user_id,
            kind="MATCH_FOUND",
            text=(
                f"🤝 Есть отклик!\n\n"
                f"{other_user.display_name} — на «{about}»\n\n"
                f"Написать: {handle}"
            ),
            dedup_key=f"match:{min(user_a, user_b)}:{max(user_a, user_b)}:{me}",
            open_app_label="Открыть отклики",
        )


async def run_buddy_matcher(session: AsyncSession, limit: int = 20) -> int:
    """Назначает первокурсникам наставников-старшекурсников.

    Страховка от пустой колоды: матч гарантирован даже когда в базе три человека.
    """
    res = await session.execute(
        select(MatchProfile, Student, AppUser)
        .join(AppUser, AppUser.id == MatchProfile.app_user_id)
        .join(Binding, Binding.app_user_id == MatchProfile.app_user_id)
        .join(Student, Student.id == Binding.student_id)
        .where(MatchProfile.wants_mentor.is_(True), MatchProfile.visible.is_(True))
        .limit(limit)
    )
    seekers = list(res.all())
    if not seekers:
        return 0

    res = await session.execute(
        select(MatchProfile, Student, AppUser)
        .join(AppUser, AppUser.id == MatchProfile.app_user_id)
        .join(Binding, Binding.app_user_id == MatchProfile.app_user_id)
        .join(Student, Student.id == Binding.student_id)
        .where(MatchProfile.wants_mentee.is_(True), MatchProfile.visible.is_(True))
    )
    mentors = list(res.all())
    if not mentors:
        return 0

    res = await session.execute(select(MatchPair).where(MatchPair.origin == "BUDDY"))
    existing = list(res.scalars())
    paired_users = {p.a_user_id for p in existing} | {p.b_user_id for p in existing}
    mentor_load: dict[int, int] = {}
    for p in existing:
        for uid in (p.a_user_id, p.b_user_id):
            mentor_load[uid] = mentor_load.get(uid, 0) + 1

    created = 0
    for s_profile, s_student, s_user in seekers:
        if s_user.id in paired_users:
            continue

        best = None
        best_score = -100.0
        for m_profile, m_student, m_user in mentors:
            if m_user.id == s_user.id:
                continue
            if mentor_load.get(m_user.id, 0) >= (m_profile.mentee_quota or 2):
                continue
            score = 0.0
            if m_student.faculty == s_student.faculty:
                score += 3.0
            if m_student.course > s_student.course:
                score += 2.0
            score += len(set(m_profile.tags or []) & set(s_profile.tags or []))
            score -= mentor_load.get(m_user.id, 0)
            if score > best_score:
                best_score, best = score, (m_profile, m_student, m_user)

        if best is None:
            continue

        _, m_student, m_user = best
        session.add(
            MatchPair(
                a_user_id=min(s_user.id, m_user.id),
                b_user_id=max(s_user.id, m_user.id),
                intent_id=None,
                origin="BUDDY",
            )
        )
        mentor_load[m_user.id] = mentor_load.get(m_user.id, 0) + 1
        paired_users.add(s_user.id)
        created += 1

        await enqueue(
            session,
            max_user_id=s_user.max_user_id,
            kind="BUDDY_ASSIGNED",
            text=(
                f"🎓 Тебе назначен наставник\n\n"
                f"{m_student.first_name}, {m_student.course} курс, {m_student.faculty}\n"
                f"Написать: @{m_user.username or 'смотри в приложении'}\n\n"
                "Можно спрашивать про пары, преподавателей и как тут всё устроено."
            ),
            dedup_key=f"buddy:{s_user.id}:{m_user.id}",
            open_app_label="Открыть приложение",
        )
        await enqueue(
            session,
            max_user_id=m_user.max_user_id,
            kind="BUDDY_ASSIGNED",
            text=(
                f"🎓 У тебя новый подопечный\n\n"
                f"{s_student.first_name}, {s_student.course} курс, {s_student.faculty}\n"
                f"Написать: @{s_user.username or 'смотри в приложении'}\n\n"
                "Первокурснику сейчас особенно нужна пара подсказок."
            ),
            dedup_key=f"buddy:{m_user.id}:{s_user.id}",
            open_app_label="Открыть приложение",
        )

    await session.flush()
    if created:
        log.info("Buddy-матчей создано: %s", created)
    return created


async def expire_intents(session: AsyncSession) -> int:
    res = await session.execute(
        select(Intent).where(
            Intent.active.is_(True),
            Intent.expires_at.is_not(None),
            Intent.expires_at < utcnow(),
        )
    )
    n = 0
    for intent in res.scalars():
        intent.active = False
        n += 1
    if n:
        await session.flush()
    return n


def default_expiry():
    """Срок жизни объявления по умолчанию — три недели."""
    return utcnow() + timedelta(days=21)
