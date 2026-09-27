"""Pydantic-схемы API. Из них же генерируется OpenAPI и типы для фронта."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Общее ─────────────────────────────────────────────────────────


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class Ok(BaseModel):
    ok: bool = True


# ── Профиль ───────────────────────────────────────────────────────


class StudentOut(BaseModel):
    id: int
    full_name: str
    short_name: str
    first_name: str
    group_name: str
    faculty: str
    course: int
    record_book_no: str
    education_form: str
    funding: str
    # Демо-копия для экспертов (зачётка DEMO-…): синтетический профиль
    is_demo: bool = False


class StaffOut(BaseModel):
    full_name: str
    department: str
    role: str
    position: str


class MeOut(BaseModel):
    max_user_id: int
    display_name: str
    photo_url: str = ""
    is_bound: bool
    role: str
    student: StudentOut | None = None
    staff: StaffOut | None = None
    features: dict[str, bool] = Field(default_factory=dict)


class BindRequest(BaseModel):
    code: str = Field(min_length=4, max_length=16)


# ── Заявки ────────────────────────────────────────────────────────


class TemplateField(BaseModel):
    name: str
    type: str
    label: str
    required: bool = False
    options: list[str] | None = None
    placeholder: str | None = None
    hint: str | None = None
    default: Any | None = None
    min: int | None = None
    max: int | None = None
    minLength: int | None = None
    maxLength: int | None = None
    accept: list[str] | None = None
    maxSizeMb: int | None = None


class TemplateOut(BaseModel):
    key: str
    title: str
    short_title: str
    description: str
    icon: str
    category: str
    sla_days: int
    produces_document: bool
    fields: list[TemplateField] = Field(default_factory=list)


class RequestEventOut(BaseModel):
    to_status: str
    status_title: str
    actor_name: str
    actor_kind: str
    comment: str
    created_at: datetime


class DocumentOut(BaseModel):
    uuid: str
    file_name: str
    issued_by: str
    issued_at: datetime
    valid_until: datetime | None
    revoked: bool
    download_url: str
    verify_url: str


class RequestOut(BaseModel):
    id: int
    public_no: str
    template_key: str
    title: str
    icon: str
    status: str
    status_title: str
    is_active: bool
    comment: str
    created_at: datetime
    updated_at: datetime
    due_at: datetime | None
    payload: dict[str, Any] = Field(default_factory=dict)
    events: list[RequestEventOut] = Field(default_factory=list)
    document: DocumentOut | None = None
    student_name: str | None = None
    student_group: str | None = None


class CreateRequestIn(BaseModel):
    template_key: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TransitionIn(BaseModel):
    to_status: str
    comment: str = ""


class AnswerInfoIn(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)


# ── События ───────────────────────────────────────────────────────


class EventOut(BaseModel):
    id: int
    title: str
    description: str
    kind: str
    kind_title: str
    starts_at: datetime
    ends_at: datetime | None
    location: str
    organizer_name: str
    cover_url: str
    capacity: int
    taken: int
    registration_required: bool
    my_status: str | None = None
    details: dict = {}


class EventCreateIn(BaseModel):
    title: str
    description: str = ""
    kind: str = "MEETING"
    starts_at: datetime
    ends_at: datetime | None = None
    location: str = ""
    cover_url: str = ""
    capacity: int = 0
    registration_required: bool = False
    audience: dict[str, Any] = Field(default_factory=dict)


# ── Возможности ───────────────────────────────────────────────────


class OpportunityOut(BaseModel):
    id: int
    title: str
    description: str
    kind: str
    kind_title: str
    level: str
    level_title: str
    organizer: str
    url: str
    cover_url: str
    registration_deadline: datetime | None
    days_left: int | None
    team_size_min: int
    team_size_max: int
    prize_text: str
    tags: list[str]
    moderation_status: str
    source: str
    my_interest: str | None = None
    score: float = 0.0
    details: dict = {}


class OpportunityCreateIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    kind: str = "HACKATHON"
    level: str = "CITY"
    organizer: str = ""
    url: str = ""
    registration_deadline: datetime | None = None
    team_size_min: int = 1
    team_size_max: int = 1
    prize_text: str = ""
    tags: list[str] = Field(default_factory=list)


class InterestIn(BaseModel):
    level: str = "INTERESTED"


class LookingForTeamIn(BaseModel):
    message: str = Field(default="", max_length=500)


# ── Матчинг ───────────────────────────────────────────────────────


class IntentOut(BaseModel):
    id: int
    kind: str
    kind_title: str
    title: str
    description: str
    tags: list[str]
    author_name: str
    author_photo: str = ""
    author_course: int | None = None
    author_faculty: str | None = None
    opportunity_title: str | None = None
    created_at: datetime
    score: float = 0.0


class IntentCreateIn(BaseModel):
    kind: str = "STUDY_BUDDY"
    title: str = Field(min_length=3, max_length=160)
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class SwipeIn(BaseModel):
    intent_id: int
    decision: str = Field(pattern="^(LIKE|SKIP)$")


class SwipeOut(BaseModel):
    matched: bool
    match_name: str | None = None
    match_username: str | None = None


class MatchOut(BaseModel):
    id: int
    origin: str
    partner_name: str
    partner_username: str
    partner_photo: str = ""
    about: str
    created_at: datetime


class MatchProfileIn(BaseModel):
    bio: str = ""
    tags: list[str] = Field(default_factory=list)
    district: str = ""
    wants_mentor: bool = False
    wants_mentee: bool = False
    visible: bool = True


# ── Ассистент ─────────────────────────────────────────────────────


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class SourceOut(BaseModel):
    title: str
    url: str = ""
    snippet: str = ""


class AskOut(BaseModel):
    answer: str
    sources: list[SourceOut] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)


class ChatMessageOut(BaseModel):
    role: str
    content: str
    sources: list[SourceOut] = Field(default_factory=list)
    created_at: datetime


class ChatHistoryOut(BaseModel):
    messages: list[ChatMessageOut] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


# ── Главная ───────────────────────────────────────────────────────


class HomeOut(BaseModel):
    greeting: str
    active_requests: list[RequestOut] = Field(default_factory=list)
    upcoming_events: list[EventOut] = Field(default_factory=list)
    recommended: list[OpportunityOut] = Field(default_factory=list)
    deck_size: int = 0
    new_matches: int = 0


# ── Проверка документа ────────────────────────────────────────────


class VerifyOut(BaseModel):
    found: bool
    valid: bool
    reason: str = ""
    document_title: str | None = None
    number: str | None = None
    student_name: str | None = None
    student_group: str | None = None
    issued_by: str | None = None
    issued_at: datetime | None = None
    valid_until: datetime | None = None
