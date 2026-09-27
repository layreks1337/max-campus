"""Учёба и жизнь группы: расписание, «мой день», баллы, корпуса, билеты,
календарь, «поделиться» и опросы старосты."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import logging
from datetime import date, datetime, timedelta

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.core.config import settings
from app.core.dates import UNIVERSITY_TZ, local, when_full_ru
from app.core.deps import BoundUserDep, SessionDep, StaffUserDep
from app.db.models import (
    REG_ATTENDED,
    REG_REGISTERED,
    AppUser,
    Binding,
    Building,
    CalendarEvent,
    EventRegistration,
    GradeItem,
    GroupHead,
    GroupPoll,
    PollVote,
    Request,
    ScheduleSlot,
    Student,
    utcnow,
)
from app.integrations.max.client import app_url_for, bot_username
from app.modules.demo.service import demo_filter, demo_student_ids, is_demo
from app.modules.notify.service import enqueue

log = logging.getLogger("api.campus")
router = APIRouter(tags=["campus"])
public_router = APIRouter(tags=["public"])

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


def _not_found(message: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": message})


# ══════════════════════════════════════════════════════════════════
#  Расписание
# ══════════════════════════════════════════════════════════════════


class SlotOut(BaseModel):
    id: int
    pair_no: int
    starts: str
    ends: str
    subject: str
    kind: str
    teacher: str
    room: str
    building_code: str
    building_name: str


class DayOut(BaseModel):
    date: date
    weekday: str
    is_today: bool
    slots: list[SlotOut]


class WeekOut(BaseModel):
    group_name: str
    week_no: int
    parity: str
    days: list[DayOut]


def _week_no(d: date) -> int:
    """Номер учебной недели: первая — та, в которую попало 1 сентября."""
    year = d.year if d.month >= 9 else d.year - 1
    start = date(year, 9, 1)
    start -= timedelta(days=start.weekday())
    return max(1, (d - start).days // 7 + 1)


def _parity(d: date) -> str:
    return "odd" if _week_no(d) % 2 == 1 else "even"


def _today() -> date:
    return utcnow().astimezone(UNIVERSITY_TZ).date()


async def _buildings(session) -> dict[str, Building]:
    return {b.code: b for b in (await session.execute(select(Building))).scalars()}


async def _slots(session, group_name: str) -> list[ScheduleSlot]:
    res = await session.execute(
        select(ScheduleSlot)
        .where(ScheduleSlot.group_name == group_name)
        .order_by(ScheduleSlot.weekday, ScheduleSlot.pair_no)
    )
    return list(res.scalars())


def _slot_out(s: ScheduleSlot, buildings: dict[str, Building]) -> SlotOut:
    b = buildings.get(s.building_code)
    return SlotOut(
        id=s.id, pair_no=s.pair_no, starts=s.starts, ends=s.ends, subject=s.subject,
        kind=s.kind, teacher=s.teacher, room=s.room, building_code=s.building_code,
        building_name=b.name if b else "",
    )


def _day_slots(slots: list[ScheduleSlot], d: date) -> list[ScheduleSlot]:
    parity = _parity(d)
    return [s for s in slots if s.weekday == d.weekday() and s.parity in ("any", parity)]


@router.get("/schedule", response_model=WeekOut, summary="Расписание группы на неделю")
async def schedule(current: BoundUserDep, session: SessionDep, week: int = 0) -> WeekOut:
    today = _today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week)
    slots = await _slots(session, current.student.group_name)
    buildings = await _buildings(session)
    days = []
    for i in range(6):
        d = monday + timedelta(days=i)
        days.append(DayOut(
            date=d, weekday=WEEKDAYS[i], is_today=d == today,
            slots=[_slot_out(s, buildings) for s in _day_slots(slots, d)],
        ))
    return WeekOut(
        group_name=current.student.group_name,
        week_no=_week_no(monday),
        parity=_parity(monday),
        days=days,
    )


# ══════════════════════════════════════════════════════════════════
#  Мой день
# ══════════════════════════════════════════════════════════════════


class TodayItem(BaseModel):
    kind: str  # pair | event | deadline | request
    time: str
    ends: str = ""
    title: str
    subtitle: str = ""
    state: str = ""  # now | next | done | ""
    ref: str = ""  # номер заявки или id события — для перехода


class TodayOut(BaseModel):
    date: date
    weekday: str
    week_no: int
    parity: str
    now: SlotOut | None
    next: SlotOut | None
    next_day_label: str = ""
    items: list[TodayItem]


def _hm(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


@router.get("/today", response_model=TodayOut, summary="Мой день: пары, события, дедлайны")
async def today(current: BoundUserDep, session: SessionDep) -> TodayOut:
    now_local = utcnow().astimezone(UNIVERSITY_TZ)
    d = now_local.date()
    minutes = now_local.hour * 60 + now_local.minute
    slots = await _slots(session, current.student.group_name)
    buildings = await _buildings(session)
    todays = _day_slots(slots, d)

    now_slot = next((s for s in todays if _hm(s.starts) <= minutes < _hm(s.ends)), None)
    next_slot = next((s for s in todays if _hm(s.starts) > minutes), None)
    next_label = "сегодня" if next_slot else ""
    if next_slot is None:
        for shift in range(1, 8):
            day = d + timedelta(days=shift)
            found = _day_slots(slots, day)
            if found:
                next_slot = found[0]
                next_label = "завтра" if shift == 1 else WEEKDAYS[day.weekday()].lower()
                break

    items: list[TodayItem] = []
    for s in todays:
        state = "now" if s is now_slot else ("done" if _hm(s.ends) <= minutes else "")
        if s is next_slot and next_label == "сегодня":
            state = "next"
        place = f"ауд. {s.room}" if s.room[:1].isdigit() else s.room
        items.append(TodayItem(
            kind="pair", time=s.starts, ends=s.ends, title=s.subject,
            subtitle=f"{s.kind} · {place} · {s.teacher}", state=state,
        ))

    # События сегодня, на которые записан студент
    day_start = datetime(d.year, d.month, d.day, tzinfo=UNIVERSITY_TZ)
    day_end = day_start + timedelta(days=1)
    res = await session.execute(
        select(CalendarEvent, EventRegistration.status)
        .outerjoin(
            EventRegistration,
            (EventRegistration.event_id == CalendarEvent.id)
            & (EventRegistration.student_id == current.student.id),
        )
        .where(CalendarEvent.starts_at >= day_start, CalendarEvent.starts_at < day_end)
    )
    for ev, reg in res.all():
        is_deadline = ev.kind == "DEADLINE"
        if not is_deadline and reg != REG_REGISTERED:
            continue
        items.append(TodayItem(
            kind="deadline" if is_deadline else "event",
            time=local(ev.starts_at).strftime("%H:%M"),
            title=ev.title,
            subtitle=ev.location,
            ref=str(ev.id),
        ))

    # Заявки, где что-то ждёт студента
    res = await session.execute(
        select(Request).where(
            Request.student_id == current.student.id,
            Request.status.in_(["READY", "NEEDS_INFO"]),
        )
    )
    for r in res.scalars():
        items.append(TodayItem(
            kind="request", time="",
            title="Справка готова" if r.status == "READY" else "Деканат просит уточнить",
            subtitle=f"№{r.public_no}", ref=r.public_no,
        ))

    items.sort(key=lambda i: (i.time == "", i.time))
    return TodayOut(
        date=d, weekday=WEEKDAYS[d.weekday()], week_no=_week_no(d), parity=_parity(d),
        now=_slot_out(now_slot, buildings) if now_slot else None,
        next=_slot_out(next_slot, buildings) if next_slot else None,
        next_day_label=next_label,
        items=items,
    )


# ══════════════════════════════════════════════════════════════════
#  Успеваемость
# ══════════════════════════════════════════════════════════════════


class GradeItemOut(BaseModel):
    title: str
    points: int
    max_points: int
    graded_at: datetime


class SubjectOut(BaseModel):
    subject: str
    control: str
    teacher: str
    points: int
    max_points: int
    forecast: str
    items: list[GradeItemOut]


class GradesOut(BaseModel):
    semester: str
    total_points: int
    total_max: int
    subjects: list[SubjectOut]


def _forecast(points: int, maximum: int, control: str) -> str:
    """Прогноз по доле набранного, как в БРС: 85% — отлично, 70% — хорошо, 55% — зачёт/удовл."""
    share = points / maximum if maximum else 0
    if control == "Зачёт":
        return "идёт на зачёт" if share >= 0.55 else "есть риск незачёта"
    if share >= 0.85:
        return "идёт на «отлично»"
    if share >= 0.7:
        return "идёт на «хорошо»"
    if share >= 0.55:
        return "идёт на «удовлетворительно»"
    return "нужно подтянуть"


@router.get("/grades", response_model=GradesOut, summary="Баллы по предметам")
async def grades(current: BoundUserDep, session: SessionDep) -> GradesOut:
    res = await session.execute(
        select(GradeItem)
        .where(GradeItem.student_id == current.student.id)
        .order_by(GradeItem.subject, GradeItem.graded_at)
    )
    by_subject: dict[str, list[GradeItem]] = {}
    for g in res.scalars():
        by_subject.setdefault(g.subject, []).append(g)

    subjects = []
    for name, items in by_subject.items():
        pts = sum(i.points for i in items)
        mx = sum(i.max_points for i in items)
        subjects.append(SubjectOut(
            subject=name, control=items[0].control, teacher=items[0].teacher,
            points=pts, max_points=mx, forecast=_forecast(pts, mx, items[0].control),
            items=[GradeItemOut(title=i.title, points=i.points, max_points=i.max_points,
                                graded_at=i.graded_at) for i in items],
        ))
    d = _today()
    semester = f"Осенний семестр {d.year}/{d.year + 1}" if d.month >= 9 else f"Весенний семестр {d.year}"
    return GradesOut(
        semester=semester,
        total_points=sum(s.points for s in subjects),
        total_max=sum(s.max_points for s in subjects),
        subjects=subjects,
    )


# ══════════════════════════════════════════════════════════════════
#  Корпуса
# ══════════════════════════════════════════════════════════════════


class BuildingOut(BaseModel):
    code: str
    name: str
    address: str
    hint: str
    floors: int
    cover_url: str
    map_url: str


@router.get("/buildings", response_model=list[BuildingOut], summary="Корпуса и как найти аудиторию")
async def buildings(current: BoundUserDep, session: SessionDep) -> list[BuildingOut]:
    from urllib.parse import quote

    res = await session.execute(select(Building).order_by(Building.id))
    return [
        BuildingOut(
            code=b.code, name=b.name, address=b.address, hint=b.hint, floors=b.floors,
            cover_url=b.cover_url,
            map_url=f"https://yandex.ru/maps/?text={quote(b.address)}",
        )
        for b in res.scalars()
    ]


# ══════════════════════════════════════════════════════════════════
#  Билет на событие
# ══════════════════════════════════════════════════════════════════


class TicketOut(BaseModel):
    code: str
    qr_svg: str
    event_id: int
    event_title: str
    when: str
    location: str
    holder: str
    status: str


def _sign(reg_id: int) -> str:
    mac = hmac.new(settings.MAX_WEBHOOK_SECRET.encode(), f"ticket:{reg_id}".encode(), hashlib.sha256)
    return base64.b32encode(mac.digest()).decode()[:5]


def ticket_code(reg_id: int) -> str:
    """Короткий код: номер записи + подпись. Подделать без секрета нельзя,
    а продиктовать на входе — можно."""
    return f"T{reg_id}-{_sign(reg_id)}"


def _qr_svg(data: str) -> str:
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


@router.get("/events/{event_id}/ticket", response_model=TicketOut, summary="Билет на событие")
async def event_ticket(event_id: int, current: BoundUserDep, session: SessionDep) -> TicketOut:
    res = await session.execute(
        select(EventRegistration, CalendarEvent)
        .join(CalendarEvent, CalendarEvent.id == EventRegistration.event_id)
        .where(
            EventRegistration.event_id == event_id,
            EventRegistration.student_id == current.student.id,
            EventRegistration.status.in_([REG_REGISTERED, REG_ATTENDED]),
        )
    )
    row = res.first()
    if row is None:
        raise _not_found("Билет появится после записи на событие")
    reg, ev = row
    code = ticket_code(reg.id)
    return TicketOut(
        code=code, qr_svg=_qr_svg(code), event_id=ev.id, event_title=ev.title,
        when=when_full_ru(ev.starts_at), location=ev.location,
        holder=current.student.full_name, status=reg.status,
    )


class TicketCheckIn(BaseModel):
    code: str = Field(min_length=3, max_length=40)


class TicketCheckOut(BaseModel):
    ok: bool
    already: bool
    holder: str
    group_name: str
    event_title: str


@router.post("/staff/tickets/check", response_model=TicketCheckOut, summary="Проверить билет на входе")
async def check_ticket(body: TicketCheckIn, current: StaffUserDep, session: SessionDep) -> TicketCheckOut:
    raw = body.code.strip().upper().replace(" ", "")
    try:
        num, sig = raw.removeprefix("T").split("-", 1)
        reg_id = int(num)
    except ValueError:
        raise HTTPException(400, detail={"code": "BAD_TICKET", "message": "Код билета не распознан"})
    if not hmac.compare_digest(sig, _sign(reg_id)):
        raise HTTPException(400, detail={"code": "BAD_TICKET", "message": "Билет недействителен"})

    res = await session.execute(
        select(EventRegistration, CalendarEvent, Student)
        .join(CalendarEvent, CalendarEvent.id == EventRegistration.event_id)
        .join(Student, Student.id == EventRegistration.student_id)
        .where(EventRegistration.id == reg_id)
    )
    row = res.first()
    if row is None:
        raise _not_found("Запись не найдена — возможно, её отменили")
    reg, ev, st = row
    if reg.status not in (REG_REGISTERED, REG_ATTENDED):
        raise HTTPException(409, detail={"code": "CANCELLED", "message": "Запись на событие отменена"})
    already = reg.status == REG_ATTENDED
    reg.status = REG_ATTENDED
    await session.commit()
    return TicketCheckOut(ok=True, already=already, holder=st.full_name,
                          group_name=st.group_name, event_title=ev.title)


# ══════════════════════════════════════════════════════════════════
#  Календарь телефона и «поделиться»
# ══════════════════════════════════════════════════════════════════


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@public_router.get("/ics/event/{event_id}.ics", summary="Событие в календарь телефона")
async def event_ics(event_id: int, session: SessionDep) -> Response:
    ev = await session.get(CalendarEvent, event_id)
    if ev is None or ev.status != "PUBLISHED":
        raise _not_found("Событие не найдено")
    fmt = "%Y%m%dT%H%M%SZ"
    end = ev.ends_at or ev.starts_at + timedelta(hours=1)
    body = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Campus//MAX//RU",
        "BEGIN:VEVENT",
        f"UID:campus-event-{ev.id}@campus",
        f"DTSTAMP:{utcnow().strftime(fmt)}",
        f"DTSTART:{ev.starts_at.strftime(fmt)}",
        f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:{_ics_escape(ev.title)}",
        f"DESCRIPTION:{_ics_escape(ev.description)}",
        f"LOCATION:{_ics_escape(ev.location)}",
        "BEGIN:VALARM",
        "TRIGGER:-PT1H",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_ics_escape(ev.title)}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ])
    return Response(
        content=body.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="event-{ev.id}.ics"'},
    )


class ShareOut(BaseModel):
    sent_to_chat: bool
    text: str
    link: str


async def app_link(param: str) -> str:
    """Ссылка, открывающая мини-приложение сразу на нужном экране."""
    name = await bot_username()
    if name:
        return f"https://max.ru/{name}?startapp={param}"
    # Имя бота не узнать (пусто в настройках и MAX недоступен) — ссылка на само
    # приложение: браузер откроет тот же экран по WebAppStartParam
    public_url = settings.MINIAPP_PUBLIC_URL.strip().rstrip("/")
    return app_url_for(0, public_url, signed=False, start_param=param)


@router.post("/events/{event_id}/share", response_model=ShareOut, summary="Поделиться событием")
async def share_event(event_id: int, current: BoundUserDep, session: SessionDep) -> ShareOut:
    """Бот присылает карточку события в личный чат — дальше её пересылают
    в чат группы обычным «Переслать». Писать в чужие чаты бот не может,
    а пересылка из лички работает везде."""
    ev = await session.get(CalendarEvent, event_id)
    if ev is None:
        raise _not_found("Событие не найдено")
    link = await app_link(f"event_{ev.id}")
    text = f"📅 {ev.title}\n{when_full_ru(ev.starts_at)}"
    if ev.location:
        text += f" · {ev.location}"
    text += f"\n\nПодробности и запись — в Кампусе:\n{link}"
    item = await enqueue(
        session,
        max_user_id=current.app_user.max_user_id,
        kind="share_event",
        text=text,
        dedup_key=f"share:{current.app_user.id}:{ev.id}:{utcnow().strftime('%Y%m%d%H%M')}",
        open_app_label="Открыть событие",
        open_app_payload=f"event_{ev.id}",
    )
    await session.commit()
    return ShareOut(sent_to_chat=item is not None, text=text, link=link)


# ══════════════════════════════════════════════════════════════════
#  Группа и опросы старосты
# ══════════════════════════════════════════════════════════════════


class PollOut(BaseModel):
    id: int
    question: str
    options: list[str]
    counts: list[int]
    my_vote: int | None
    voted: int
    closes_at: datetime | None
    event_id: int | None
    mine: bool


class GroupOut(BaseModel):
    group_name: str
    members: int
    is_head: bool
    head_name: str
    polls: list[PollOut]
    # Демо-профиль: опросы видит только автор, рассылки группе нет
    demo: bool = False


class PollIn(BaseModel):
    question: str = Field(min_length=3, max_length=300)
    options: list[str] = Field(min_length=2, max_length=6)
    event_id: int | None = None


class VoteIn(BaseModel):
    option_idx: int = Field(ge=0, le=5)


async def _head(session, group_name: str) -> Student | None:
    """Настоящий староста группы. Демо-копии тоже старосты — эксперт должен
    увидеть экран опросов, — но для остальных старостой остаётся оригинал."""
    res = await session.execute(
        select(Student).join(GroupHead, GroupHead.student_id == Student.id)
        .where(GroupHead.group_name == group_name, ~demo_filter())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def _is_head(session, st: Student) -> bool:
    res = await session.execute(
        select(GroupHead.id).where(GroupHead.student_id == st.id, GroupHead.group_name == st.group_name)
    )
    return res.first() is not None


async def _poll_out(session, poll: GroupPoll, student_id: int) -> PollOut:
    # Голоса других демо-копий не считаем: полсотни экспертов в группе из трёх
    # человек превратили бы опрос в бессмыслицу
    res = await session.execute(
        select(PollVote).where(
            PollVote.poll_id == poll.id,
            or_(PollVote.student_id == student_id, PollVote.student_id.not_in(demo_student_ids())),
        )
    )
    votes = list(res.scalars())
    counts = [0] * len(poll.options)
    mine = None
    for v in votes:
        if 0 <= v.option_idx < len(counts):
            counts[v.option_idx] += 1
        if v.student_id == student_id:
            mine = v.option_idx
    return PollOut(
        id=poll.id, question=poll.question, options=list(poll.options), counts=counts,
        my_vote=mine, voted=len(votes), closes_at=poll.closes_at, event_id=poll.event_id,
        mine=poll.author_student_id == student_id,
    )


@router.get("/group", response_model=GroupOut, summary="Моя группа и опросы")
async def my_group(current: BoundUserDep, session: SessionDep) -> GroupOut:
    st = current.student
    # Демо-копии в счётчик не входят — кроме самого смотрящего
    members = (await session.execute(
        select(func.count(Student.id)).where(
            Student.group_name == st.group_name, or_(~demo_filter(), Student.id == st.id)
        )
    )).scalar() or 0
    is_head = await _is_head(session, st)
    head = st if is_head else await _head(session, st.group_name)
    # Опросы демо-копий видит только их автор
    res = await session.execute(
        select(GroupPoll).where(
            GroupPoll.group_name == st.group_name,
            or_(
                GroupPoll.author_student_id == st.id,
                GroupPoll.author_student_id.not_in(demo_student_ids()),
            ),
        )
        .order_by(GroupPoll.created_at.desc()).limit(10)
    )
    polls = [await _poll_out(session, p, st.id) for p in res.scalars()]
    return GroupOut(
        group_name=st.group_name, members=members,
        is_head=is_head,
        head_name=head.short_name if head else "",
        polls=polls,
        demo=is_demo(st),
    )


@router.post("/group/polls", response_model=PollOut, status_code=201, summary="Опрос для группы")
async def create_poll(body: PollIn, current: BoundUserDep, session: SessionDep) -> PollOut:
    st = current.student
    if not await _is_head(session, st):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Опросы создаёт староста группы"})
    options = [o.strip() for o in body.options if o.strip()]
    if len(options) < 2:
        raise HTTPException(422, detail={"code": "VALIDATION", "message": "Нужно хотя бы два варианта"})
    poll = GroupPoll(
        group_name=st.group_name, author_student_id=st.id, question=body.question.strip(),
        options=options, event_id=body.event_id, closes_at=utcnow() + timedelta(days=3),
    )
    session.add(poll)
    await session.flush()

    # Одногруппникам — сообщение от бота с кнопкой в приложение. Демо-копии
    # не получают ничего, а опрос демо-старосты не уходит никому: его видит
    # только автор, и один эксперт не заспамит остальных в MAX.
    recipients = []
    if not is_demo(st):
        res = await session.execute(
            select(AppUser.max_user_id)
            .join(Binding, Binding.app_user_id == AppUser.id)
            .join(Student, Student.id == Binding.student_id)
            .where(Student.group_name == st.group_name, Student.id != st.id, ~demo_filter())
        )
        recipients = [row[0] for row in res.all()]
    for max_user_id in recipients:
        await enqueue(
            session, max_user_id=max_user_id, kind="group_poll",
            text=f"🗳 Староста {st.short_name} спрашивает группу {st.group_name}:\n\n{poll.question}",
            dedup_key=f"poll:{poll.id}:{max_user_id}",
            open_app_label="Ответить", open_app_payload="group", respect_quiet_hours=True,
        )
    await session.commit()
    return await _poll_out(session, poll, st.id)


@router.post("/group/polls/{poll_id}/vote", response_model=PollOut, summary="Проголосовать")
async def vote(poll_id: int, body: VoteIn, current: BoundUserDep, session: SessionDep) -> PollOut:
    poll = await session.get(GroupPoll, poll_id)
    if poll is None or poll.group_name != current.student.group_name:
        raise _not_found("Опрос не найден")
    if body.option_idx >= len(poll.options):
        raise HTTPException(422, detail={"code": "VALIDATION", "message": "Нет такого варианта"})
    res = await session.execute(
        select(PollVote).where(PollVote.poll_id == poll.id, PollVote.student_id == current.student.id)
    )
    existing = res.scalar_one_or_none()
    if existing:
        existing.option_idx = body.option_idx
    else:
        session.add(PollVote(poll_id=poll.id, student_id=current.student.id, option_idx=body.option_idx))
    await session.commit()
    return await _poll_out(session, poll, current.student.id)
