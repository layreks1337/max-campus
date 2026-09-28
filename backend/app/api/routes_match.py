"""Матчинг: колода интентов, свайпы, отклики, профиль."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api import serializers
from app.api.schemas import (
    IntentCreateIn,
    IntentOut,
    MatchOut,
    MatchProfileIn,
    Ok,
    SwipeIn,
    SwipeOut,
)
from app.core.deps import BoundUserDep, SessionDep
from app.db.models import (
    AppUser,
    Binding,
    Intent,
    MatchPair,
    MatchProfile,
    Student,
    utcnow,
)
from app.modules.match import service as match_service

log = logging.getLogger("api.match")
router = APIRouter(prefix="/match", tags=["match"])


@router.get("/deck", response_model=list[IntentOut], summary="Колода интентов")
async def get_deck(
    current: BoundUserDep, session: SessionDep, limit: int = Query(20, ge=1, le=50)
) -> list[IntentOut]:
    rows = await match_service.get_deck(
        session,
        app_user_id=current.app_user.id,
        student=current.student,
        limit=limit,
    )
    return [serializers.intent_out(i, author, score) for i, author, score in rows]


@router.post("/swipe", response_model=SwipeOut, summary="Свайп по карточке")
async def swipe(body: SwipeIn, current: BoundUserDep, session: SessionDep) -> SwipeOut:
    pair = await match_service.register_swipe(
        session,
        app_user_id=current.app_user.id,
        intent_id=body.intent_id,
        decision=body.decision,
    )
    if pair is None:
        return SwipeOut(matched=False)

    other_id = pair.b_user_id if pair.a_user_id == current.app_user.id else pair.a_user_id
    other = await session.get(AppUser, other_id)
    simulated = match_service.is_synthetic(other)
    return SwipeOut(
        matched=True,
        match_name=other.display_name if other else None,
        match_username=None if simulated or other is None else other.username,
        simulated=simulated,
    )


@router.get("/matches", response_model=list[MatchOut], summary="Мои отклики")
async def my_matches(current: BoundUserDep, session: SessionDep) -> list[MatchOut]:
    res = await session.execute(
        select(MatchPair)
        .where(
            (MatchPair.a_user_id == current.app_user.id)
            | (MatchPair.b_user_id == current.app_user.id)
        )
        .order_by(MatchPair.created_at.desc())
    )
    pairs = list(res.scalars())
    if not pairs:
        return []

    other_ids = {
        p.b_user_id if p.a_user_id == current.app_user.id else p.a_user_id for p in pairs
    }
    res = await session.execute(select(AppUser).where(AppUser.id.in_(other_ids)))
    users = {u.id: u for u in res.scalars()}

    out: list[MatchOut] = []
    for p in pairs:
        oid = p.b_user_id if p.a_user_id == current.app_user.id else p.a_user_id
        user = users.get(oid)
        if user is None:
            continue
        about = "Наставничество"
        if p.intent_id:
            intent = await session.get(Intent, p.intent_id)
            if intent:
                about = intent.title
        simulated = match_service.is_synthetic(user)
        out.append(
            MatchOut(
                id=p.id,
                origin=p.origin,
                partner_name=user.display_name,
                # @demo_… в MAX не существует — кнопку «Написать» не показываем
                partner_username="" if simulated else (user.username or ""),
                partner_photo=user.photo_url or "",
                about=about,
                created_at=p.created_at,
                simulated=simulated,
            )
        )
    return out


@router.get("/intents", response_model=list[IntentOut], summary="Мои объявления")
async def my_intents(current: BoundUserDep, session: SessionDep) -> list[IntentOut]:
    res = await session.execute(
        select(Intent)
        .where(Intent.author_user_id == current.app_user.id)
        .order_by(Intent.created_at.desc())
    )
    return [serializers.intent_out(i, current.student) for i in res.scalars()]


@router.post("/intents", response_model=IntentOut, status_code=201, summary="Создать объявление")
async def create_intent(
    body: IntentCreateIn, current: BoundUserDep, session: SessionDep
) -> IntentOut:
    intent = Intent(
        author_user_id=current.app_user.id,
        kind=body.kind,
        title=body.title,
        description=body.description,
        tags=body.tags,
        expires_at=utcnow() + timedelta(days=21),
    )
    session.add(intent)
    await session.flush()
    await session.refresh(intent, ["author", "opportunity"])
    return serializers.intent_out(intent, current.student)


@router.delete("/intents/{intent_id}", response_model=Ok, summary="Снять объявление")
async def close_intent(intent_id: int, current: BoundUserDep, session: SessionDep) -> Ok:
    intent = await session.get(Intent, intent_id)
    if intent is None or intent.author_user_id != current.app_user.id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Не найдено"})
    intent.active = False
    await session.flush()
    return Ok()


@router.get("/profile", response_model=MatchProfileIn, summary="Мой профиль знакомств")
async def get_profile(current: BoundUserDep, session: SessionDep) -> MatchProfileIn:
    res = await session.execute(
        select(MatchProfile).where(MatchProfile.app_user_id == current.app_user.id)
    )
    p = res.scalar_one_or_none()
    if p is None:
        return MatchProfileIn(wants_mentor=current.student.course == 1)
    return MatchProfileIn(
        bio=p.bio,
        tags=list(p.tags or []),
        district=p.district,
        wants_mentor=p.wants_mentor,
        wants_mentee=p.wants_mentee,
        visible=p.visible,
    )


@router.put("/profile", response_model=MatchProfileIn, summary="Сохранить профиль")
async def save_profile(
    body: MatchProfileIn, current: BoundUserDep, session: SessionDep
) -> MatchProfileIn:
    res = await session.execute(
        select(MatchProfile).where(MatchProfile.app_user_id == current.app_user.id)
    )
    p = res.scalar_one_or_none()
    if p is None:
        p = MatchProfile(app_user_id=current.app_user.id)
        session.add(p)

    p.bio = body.bio
    p.tags = body.tags
    p.district = body.district
    p.wants_mentor = body.wants_mentor
    p.wants_mentee = body.wants_mentee
    p.visible = body.visible
    await session.flush()

    # Попросил наставника — подбираем сразу ему, не дожидаясь фонового прохода
    if body.wants_mentor:
        try:
            await match_service.run_buddy_matcher(session, seeker_user_id=current.app_user.id)
        except Exception:
            log.exception("Не удалось подобрать наставника сразу")

    return body
