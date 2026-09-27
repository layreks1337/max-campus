"""Модели данных MAX Campus.

Все модели в одном файле сознательно: проект небольшой, так быстрее ориентироваться,
чем прыгать по десятку модулей. Статусы — строковые константы, а не Enum-типы БД:
меняются без миграции, что на хакатоне важнее строгости.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ══════════════════════════════════════════════════════════════════
#  Справочники и ядро
# ══════════════════════════════════════════════════════════════════


class Student(Base):
    """Справочник студентов вуза. Сидируется, в проде приезжает из деканата."""

    __tablename__ = "student"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_name: Mapped[str] = mapped_column(String(80))
    first_name: Mapped[str] = mapped_column(String(80))
    middle_name: Mapped[str] = mapped_column(String(80), default="")
    group_name: Mapped[str] = mapped_column(String(32), index=True)
    faculty: Mapped[str] = mapped_column(String(64), index=True)
    course: Mapped[int] = mapped_column(Integer, index=True)
    record_book_no: Mapped[str] = mapped_column(String(32), unique=True)
    birth_date: Mapped[str] = mapped_column(String(16), default="")
    education_form: Mapped[str] = mapped_column(String(32), default="очная")
    funding: Mapped[str] = mapped_column(String(32), default="бюджет")
    enrolled_year: Mapped[int] = mapped_column(Integer, default=2026)

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p)

    @property
    def short_name(self) -> str:
        # Демо-копия без фамилии в профиле MAX: «Даниил», а не «Д.»
        if not self.last_name:
            return self.first_name
        initials = "".join(f"{p[0]}." for p in (self.first_name, self.middle_name) if p)
        return f"{self.last_name} {initials}".strip()


class AppUser(Base):
    """Пользователь мини-приложения — идентичность из MAX."""

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(80), default="")
    last_name: Mapped[str] = mapped_column(String(80), default="")
    username: Mapped[str] = mapped_column(String(80), default="")
    photo_url: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    binding: Mapped[Binding | None] = relationship(back_populates="app_user", uselist=False)
    staff: Mapped[Staff | None] = relationship(back_populates="app_user", uselist=False)

    @property
    def display_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p) or self.username


class Binding(Base):
    """Мост между аккаунтом MAX и студентом вуза. Без него справку выдать некому."""

    __tablename__ = "binding"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), unique=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), unique=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    method: Mapped[str] = mapped_column(String(32), default="code")

    app_user: Mapped[AppUser] = relationship(back_populates="binding")
    student: Mapped[Student] = relationship()


class BindingCode(Base):
    """Одноразовый код привязки, выдаётся деканатом."""

    __tablename__ = "binding_code"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    student: Mapped[Student] = relationship()


# Роли
ROLE_STUDENT = "STUDENT"
ROLE_CLERK = "STAFF_CLERK"
ROLE_HEAD = "STAFF_HEAD"
ROLE_ORGANIZER = "ORGANIZER"
ROLE_MODERATOR = "MODERATOR"
ROLE_ADMIN = "ADMIN"
STAFF_ROLES = {ROLE_CLERK, ROLE_HEAD, ROLE_ORGANIZER, ROLE_MODERATOR, ROLE_ADMIN}


class Staff(Base):
    """Сотрудник. Роль берётся отсюда и никогда из запроса."""

    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), unique=True)
    full_name: Mapped[str] = mapped_column(String(160))
    department: Mapped[str] = mapped_column(String(120), default="Деканат")
    role: Mapped[str] = mapped_column(String(32), default=ROLE_CLERK)
    position: Mapped[str] = mapped_column(String(120), default="Специалист")

    app_user: Mapped[AppUser] = relationship(back_populates="staff")


# ══════════════════════════════════════════════════════════════════
#  Заявки
# ══════════════════════════════════════════════════════════════════

ST_DRAFT = "DRAFT"
ST_SUBMITTED = "SUBMITTED"
ST_IN_REVIEW = "IN_REVIEW"
ST_NEEDS_INFO = "NEEDS_INFO"
ST_SIGNING = "SIGNING"
ST_READY = "READY"
ST_ISSUED = "ISSUED"
ST_REJECTED = "REJECTED"
ST_CANCELLED = "CANCELLED"

ACTIVE_STATUSES = (ST_SUBMITTED, ST_IN_REVIEW, ST_NEEDS_INFO, ST_SIGNING, ST_READY)
TERMINAL_STATUSES = (ST_ISSUED, ST_REJECTED, ST_CANCELLED)

STATUS_TITLES = {
    ST_DRAFT: "Черновик",
    ST_SUBMITTED: "Отправлена",
    ST_IN_REVIEW: "Принята в работу",
    ST_NEEDS_INFO: "Требует уточнения",
    ST_SIGNING: "На подписи",
    ST_READY: "Готова",
    ST_ISSUED: "Выдана",
    ST_REJECTED: "Отклонена",
    ST_CANCELLED: "Отменена",
}

# Разрешённые переходы машины состояний
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    ST_DRAFT: (ST_SUBMITTED, ST_CANCELLED),
    ST_SUBMITTED: (ST_IN_REVIEW, ST_REJECTED, ST_CANCELLED),
    ST_IN_REVIEW: (ST_SIGNING, ST_NEEDS_INFO, ST_REJECTED, ST_CANCELLED),
    ST_NEEDS_INFO: (ST_IN_REVIEW, ST_REJECTED, ST_CANCELLED),
    ST_SIGNING: (ST_READY, ST_NEEDS_INFO, ST_REJECTED),
    ST_READY: (ST_ISSUED,),
    ST_ISSUED: (),
    ST_REJECTED: (),
    ST_CANCELLED: (),
}


class RequestTemplate(Base):
    """Шаблон заявки. Новый тип справки = новая строка, не релиз."""

    __tablename__ = "request_template"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    short_title: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(16), default="📄")
    category: Mapped[str] = mapped_column(String(40), default="Справки")
    sla_hours: Mapped[int] = mapped_column(Integer, default=72)
    schema_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    route_json: Mapped[list] = mapped_column(JSONB, default=list)
    doc_template: Mapped[str] = mapped_column(String(64), default="generic")
    produces_document: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def fields(self) -> list[dict]:
        return (self.schema_json or {}).get("fields", [])


class Request(Base):
    """Заявка студента."""

    __tablename__ = "request"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_no: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    template_key: Mapped[str] = mapped_column(ForeignKey("request_template.key"))
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(24), default=ST_SUBMITTED, index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"), nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    template: Mapped[RequestTemplate] = relationship(lazy="joined")
    student: Mapped[Student] = relationship(lazy="joined")
    events: Mapped[list[RequestEvent]] = relationship(
        back_populates="request", order_by="RequestEvent.created_at"
    )
    document: Mapped[Document | None] = relationship(back_populates="request", uselist=False)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


class RequestEvent(Base):
    """История переходов — аудит и материал для степпера на экране."""

    __tablename__ = "request_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("request.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(24), default="")
    to_status: Mapped[str] = mapped_column(String(24))
    actor_name: Mapped[str] = mapped_column(String(160), default="")
    actor_kind: Mapped[str] = mapped_column(String(16), default="system")  # student|staff|system
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    request: Mapped[Request] = relationship(back_populates="events")


class Document(Base):
    """Выданный документ. uuid — публичный идентификатор для страницы проверки."""

    __tablename__ = "document"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("request.id"), unique=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    file_name: Mapped[str] = mapped_column(String(200))
    file_path: Mapped[str] = mapped_column(Text)
    issued_by: Mapped[str] = mapped_column(String(160), default="")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    request: Mapped[Request] = relationship(back_populates="document")


# ══════════════════════════════════════════════════════════════════
#  Календарь вуза
# ══════════════════════════════════════════════════════════════════

EV_MEETING = "MEETING"
EV_DEADLINE = "DEADLINE"
EV_CEREMONY = "CEREMONY"
EV_LECTURE = "LECTURE"
EV_SPORT = "SPORT"
EV_OTHER = "OTHER"

EVENT_KIND_TITLES = {
    EV_MEETING: "Собрание",
    EV_DEADLINE: "Дедлайн",
    EV_CEREMONY: "Мероприятие",
    EV_LECTURE: "Лекция",
    EV_SPORT: "Спорт",
    EV_OTHER: "Другое",
}

REG_REGISTERED = "REGISTERED"
REG_WAITLIST = "WAITLIST"
REG_CANCELLED = "CANCELLED"
REG_ATTENDED = "ATTENDED"


class CalendarEvent(Base):
    """Событие вуза с таргетингом по аудитории."""

    __tablename__ = "calendar_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(24), default=EV_MEETING)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str] = mapped_column(String(200), default="")
    organizer_name: Mapped[str] = mapped_column(String(160), default="")
    cover_url: Mapped[str] = mapped_column(Text, default="")
    # {"faculties": [], "courses": [], "groups": [], "only_freshmen": false} — пусто = все
    audience_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    capacity: Mapped[int] = mapped_column(Integer, default=0)  # 0 = без ограничения
    registration_required: Mapped[bool] = mapped_column(Boolean, default=False)
    registration_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Практика: адрес, расписание, шаги участия, контакт — см. DETAILS_KEYS
    details_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="PUBLISHED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    registrations: Mapped[list[EventRegistration]] = relationship(back_populates="event")


class EventRegistration(Base):
    __tablename__ = "event_registration"
    __table_args__ = (UniqueConstraint("event_id", "student_id", name="uq_event_student"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("calendar_event.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=REG_REGISTERED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    event: Mapped[CalendarEvent] = relationship(back_populates="registrations")
    student: Mapped[Student] = relationship()


# ══════════════════════════════════════════════════════════════════
#  Возможности
# ══════════════════════════════════════════════════════════════════

OPP_KINDS = {
    "HACKATHON": "Хакатон",
    "CONTEST": "Конкурс",
    "OLYMPIAD": "Олимпиада",
    "CONFERENCE": "Конференция",
    "GRANT": "Грант",
    "INTERNSHIP": "Стажировка",
    "VOLUNTEER": "Волонтёрство",
}
OPP_LEVELS = {
    "INTERNAL": "Внутривузовский",
    "CITY": "Городской",
    "REGIONAL": "Региональный",
    "FEDERAL": "Всероссийский",
    "INTERNATIONAL": "Международный",
}

MOD_PENDING = "PENDING"
MOD_APPROVED = "APPROVED"
MOD_REJECTED = "REJECTED"


class Opportunity(Base):
    __tablename__ = "opportunity"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(24), default="HACKATHON", index=True)
    level: Mapped[str] = mapped_column(String(24), default="CITY")
    organizer: Mapped[str] = mapped_column(String(160), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    cover_url: Mapped[str] = mapped_column(Text, default="")
    registration_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    team_size_min: Mapped[int] = mapped_column(Integer, default=1)
    team_size_max: Mapped[int] = mapped_column(Integer, default=1)
    prize_text: Mapped[str] = mapped_column(String(200), default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    faculties: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    source: Mapped[str] = mapped_column(String(16), default="STAFF")  # STAFF | STUDENT
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    moderation_status: Mapped[str] = mapped_column(String(16), default=MOD_APPROVED, index=True)
    moderated_by: Mapped[str] = mapped_column(String(160), default="")
    details_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OpportunityInterest(Base):
    __tablename__ = "opportunity_interest"
    __table_args__ = (UniqueConstraint("opportunity_id", "student_id", name="uq_opp_student"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunity.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    level: Mapped[str] = mapped_column(String(16), default="INTERESTED")  # INTERESTED | GOING
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ══════════════════════════════════════════════════════════════════
#  Матчинг
# ══════════════════════════════════════════════════════════════════

INTENT_KINDS = {
    "STUDY_BUDDY": "Напарник по учёбе",
    "MENTOR": "Ищу наставника",
    "MENTEE": "Готов наставлять",
    "COMMUTE": "Попутчики",
    "TEAM": "Команда на проект",
    "HOBBY": "По интересам",
}


class MatchProfile(Base):
    __tablename__ = "match_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), unique=True)
    bio: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    district: Mapped[str] = mapped_column(String(80), default="")
    wants_mentor: Mapped[bool] = mapped_column(Boolean, default=False)
    wants_mentee: Mapped[bool] = mapped_column(Boolean, default=False)
    mentee_quota: Mapped[int] = mapped_column(Integer, default=2)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    app_user: Mapped[AppUser] = relationship(lazy="joined")


class Intent(Base):
    """Карточка в колоде. Свайпаем объявления, а не людей."""

    __tablename__ = "intent"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="STUDY_BUDDY", index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunity.id"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    author: Mapped[AppUser] = relationship(lazy="joined")
    opportunity: Mapped[Opportunity | None] = relationship(lazy="joined")


class Swipe(Base):
    __tablename__ = "swipe"
    __table_args__ = (UniqueConstraint("actor_user_id", "intent_id", name="uq_swipe"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    intent_id: Mapped[int] = mapped_column(ForeignKey("intent.id"), index=True)
    decision: Mapped[str] = mapped_column(String(8))  # LIKE | SKIP
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MatchPair(Base):
    __tablename__ = "match_pair"

    id: Mapped[int] = mapped_column(primary_key=True)
    a_user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    b_user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    intent_id: Mapped[int | None] = mapped_column(ForeignKey("intent.id"), nullable=True)
    origin: Mapped[str] = mapped_column(String(16), default="SWIPE")  # SWIPE | BUDDY
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ══════════════════════════════════════════════════════════════════
#  База знаний и ассистент
# ══════════════════════════════════════════════════════════════════


class KbDocument(Base):
    __tablename__ = "kb_document"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    source_type: Mapped[str] = mapped_column(String(32), default="regulation")
    source_url: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chunks: Mapped[list[KbChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KbChunk(Base):
    __tablename__ = "kb_chunk"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("kb_document.id"), index=True)
    ord: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=True
    )

    document: Mapped[KbDocument] = relationship(back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="MINIAPP")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiMessage(Base):
    __tablename__ = "ai_message"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversation.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    sources_json: Mapped[list] = mapped_column(JSONB, default=list)
    tool_calls_json: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ══════════════════════════════════════════════════════════════════
#  Учёба: расписание, успеваемость, корпуса
# ══════════════════════════════════════════════════════════════════


class ScheduleSlot(Base):
    """Пара в расписании группы. В проде приезжает из системы расписания вуза.

    Время — местное (иркутское) строкой «HH:MM»: расписание вуза живёт в сетке
    звонков, а не в абсолютном времени, и хранить его в UTC значит на ровном
    месте получить ошибку на восемь часов.
    """

    __tablename__ = "schedule_slot"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_name: Mapped[str] = mapped_column(String(32), index=True)
    weekday: Mapped[int] = mapped_column(Integer)  # 0 — понедельник
    pair_no: Mapped[int] = mapped_column(Integer)
    starts: Mapped[str] = mapped_column(String(5))
    ends: Mapped[str] = mapped_column(String(5))
    subject: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(24), default="Лекция")
    teacher: Mapped[str] = mapped_column(String(120), default="")
    room: Mapped[str] = mapped_column(String(32), default="")
    building_code: Mapped[str] = mapped_column(String(16), default="")
    # any — каждую неделю, odd/even — только по нечётным/чётным
    parity: Mapped[str] = mapped_column(String(8), default="any")


class GradeItem(Base):
    """Контрольная точка балльно-рейтинговой системы: баллы из максимума."""

    __tablename__ = "grade_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    subject: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(120))
    points: Mapped[int] = mapped_column(Integer)
    max_points: Mapped[int] = mapped_column(Integer)
    control: Mapped[str] = mapped_column(String(16), default="Экзамен")  # итоговая форма
    teacher: Mapped[str] = mapped_column(String(120), default="")
    graded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Building(Base):
    """Учебный корпус: адрес и как найти аудиторию."""

    __tablename__ = "building"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(default=0.0)
    lon: Mapped[float] = mapped_column(default=0.0)
    hint: Mapped[str] = mapped_column(Text, default="")
    floors: Mapped[int] = mapped_column(Integer, default=4)
    cover_url: Mapped[str] = mapped_column(Text, default="")


# ══════════════════════════════════════════════════════════════════
#  Группа: опросы старосты
# ══════════════════════════════════════════════════════════════════


class GroupHead(Base):
    """Кто в группе староста. В проде — из деканата."""

    __tablename__ = "group_head"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), unique=True)
    group_name: Mapped[str] = mapped_column(String(32), index=True)


class GroupPoll(Base):
    __tablename__ = "group_poll"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_name: Mapped[str] = mapped_column(String(32), index=True)
    author_student_id: Mapped[int] = mapped_column(ForeignKey("student.id"))
    question: Mapped[str] = mapped_column(String(300))
    options: Mapped[list[str]] = mapped_column(ARRAY(String(120)))
    event_id: Mapped[int | None] = mapped_column(ForeignKey("calendar_event.id"), nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PollVote(Base):
    __tablename__ = "poll_vote"
    __table_args__ = (UniqueConstraint("poll_id", "student_id", name="uq_poll_student"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("group_poll.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"))
    option_idx: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)



# ══════════════════════════════════════════════════════════════════
#  Уведомления и аудит
# ══════════════════════════════════════════════════════════════════

OUT_PENDING = "PENDING"
OUT_SENT = "SENT"
OUT_FAILED = "FAILED"


class Outbox(Base):
    """Очередь исходящих сообщений в MAX. Единственный путь наружу."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(16), default=OUT_PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_name: Mapped[str] = mapped_column(String(160), default="")
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(40), default="")
    details_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_outbox_pending", Outbox.status, Outbox.next_attempt_at)
Index("ix_request_student_status", Request.student_id, Request.status)
Index("ix_event_starts", CalendarEvent.starts_at, CalendarEvent.status)
