"""Pydantic-схемы API. Из них же генерируется OpenAPI и типы для фронта."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ── Общее ─────────────────────────────────────────────────────────


def _web_url(value: str, *, allow_path: bool = False) -> str:
    """Ссылка из пользовательского ввода: только http(s), для обложек — ещё путь
    на своём сервере. `javascript:` и прочие схемы в ленту для всех не попадут."""
    value = value.strip()
    if not value:
        return ""
    low = value.lower()
    if low.startswith(("https://", "http://")):
        return value
    if allow_path and value.startswith("/") and not value.startswith("//"):
        return value
    raise ValueError("ссылка должна начинаться с https:// или http://")


class ErrorBody(BaseModel):
    code: str = Field(description="Машинный код ошибки: NO_AUTH, NOT_FOUND, RATE_LIMITED… — docs/06-api.md")
    message: str = Field(description="Текст для человека, по-русски")
    details: dict[str, Any] | None = Field(
        default=None, description="Подробности: у формы заявки — ошибки по полям"
    )


class ErrorResponse(BaseModel):
    """Единый конверт ошибок: так отвечает любой отказ сервера (main.py)."""

    error: ErrorBody


# Что значит код ответа — для OpenAPI. Машинные коды внутри конверта — docs/06-api.md.
ERROR_DESCRIPTIONS: dict[int, str] = {
    400: "Запрос не распознан: код билета, тип или размер вложения (BAD_TICKET, BAD_FILE_TYPE, FILE_TOO_LARGE)",
    401: "Нет заголовка авторизации, подпись не сошлась или истекла (NO_AUTH, BAD_INIT_DATA)",
    403: "Недостаточно прав для действия (FORBIDDEN, DEMO_READ_ONLY)",
    404: "Не найдено или принадлежит другому пользователю (NOT_FOUND, BAD_CODE, DEMO_DISABLED)",
    409: "Конфликт состояния (BINDING_REQUIRED, BAD_TRANSITION, ALREADY_BOUND, ATTENDED…)",
    410: "Файл документа больше недоступен (GONE)",
    413: "Тело запроса больше лимита, не дочитывается (PAYLOAD_TOO_LARGE)",
    422: "Ошибка формы или параметров (VALIDATION_FAILED)",
    429: "Превышен лимит (RATE_LIMITED, UPLOAD_QUOTA)",
    502: "Внешний сервис не ответил (STT_FAILED)",
    503: "Сервис ещё не готов или не настроен (DEMO_UNAVAILABLE, UNAVAILABLE)",
    507: "Хранилище вложений сервера заполнено (STORAGE_FULL)",
}


def errors(*codes: int, notes: dict[int, str] | None = None) -> dict[int | str, dict[str, Any]]:
    """`responses=` для роута: какие отказы он отдаёт, все — в конверте ErrorResponse.
    `notes` — своё описание кода вместо общего. 401, 403 и 409 BINDING_REQUIRED от
    зависимостей входа дописывает app/api/openapi.py."""
    notes = notes or {}
    return {
        code: {"model": ErrorResponse, "description": notes.get(code, ERROR_DESCRIPTIONS[code])}
        for code in codes
    }


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
    # Смещение времени вуза от UTC (UNIVERSITY_TZ_HOURS): по нему фронтенд считает
    # текущую пару, приветствие и даты на экранах, а не по часовому поясу телефона
    tz_offset_hours: int = 8


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
    # заполненное поле делает заявку нетиповой — её проверит сотрудник
    manual_review: bool = False


class TemplateOut(BaseModel):
    key: str
    title: str
    short_title: str
    description: str
    icon: str
    category: str
    sla_days: int
    produces_document: bool
    auto_issue: bool = False
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
    # Подписи полей из шаблона: «Военкомат», а не commissariat. Новый вид справки
    # добавляется строкой в базе — и подписи приезжают вместе с ним.
    field_labels: dict[str, str] = Field(default_factory=dict)
    events: list[RequestEventOut] = Field(default_factory=list)
    document: DocumentOut | None = None
    student_name: str | None = None
    student_group: str | None = None


class CreateRequestIn(BaseModel):
    template_key: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TransitionIn(BaseModel):
    to_status: str = Field(max_length=32)
    # Комментарий уходит студенту в чат («Что нужно: …») — длина ограничена
    comment: str = Field(default="", max_length=500)


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
    # Для окна «Поделиться» MAX (shareMaxContent): текст карточки и диплинк на событие
    share_text: str = ""
    share_link: str = ""


class EventCreateIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=4000)
    kind: str = "MEETING"
    starts_at: datetime
    ends_at: datetime | None = None
    location: str = Field(default="", max_length=200)
    cover_url: str = Field(default="", max_length=500)
    capacity: int = Field(default=0, ge=0)
    registration_required: bool = False
    audience: dict[str, Any] = Field(default_factory=dict)

    @field_validator("cover_url")
    @classmethod
    def _cover(cls, v: str) -> str:
        return _web_url(v, allow_path=True)


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
    description: str = Field(default="", max_length=4000)
    kind: str = Field(default="HACKATHON", max_length=32)
    level: str = Field(default="CITY", max_length=32)
    organizer: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=500)
    registration_deadline: datetime | None = None
    team_size_min: int = Field(default=1, ge=1, le=50)
    team_size_max: int = Field(default=1, ge=1, le=50)
    prize_text: str = Field(default="", max_length=300)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _web_url(v)


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
    kind: str = Field(default="STUDY_BUDDY", max_length=32)
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class SwipeIn(BaseModel):
    intent_id: int
    decision: str = Field(pattern="^(LIKE|SKIP)$")


class SwipeOut(BaseModel):
    matched: bool
    match_name: str | None = None
    match_username: str | None = None
    # Демо-стенд: автор синтетический, его ответ смоделирован (решение 069)
    simulated: bool = False


class MatchOut(BaseModel):
    id: int
    origin: str
    partner_name: str
    partner_username: str
    partner_photo: str = ""
    about: str
    created_at: datetime
    # Партнёр — синтетический студент сида: в MAX его нет, контакт не показывается
    simulated: bool = False


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
