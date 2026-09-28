"""Преобразование моделей в схемы API."""

from __future__ import annotations

from datetime import datetime, timezone

from app.api.schemas import (
    DocumentOut,
    EventOut,
    IntentOut,
    OpportunityOut,
    RequestEventOut,
    RequestOut,
    StudentOut,
    TemplateOut,
)
from app.core.config import settings
from app.db.models import (
    EVENT_KIND_TITLES,
    INTENT_KINDS,
    OPP_KINDS,
    OPP_LEVELS,
    STATUS_TITLES,
    CalendarEvent,
    Document,
    Intent,
    Opportunity,
    Request,
    RequestTemplate,
    Student,
)
from app.modules.demo.service import is_demo


def student_out(s: Student) -> StudentOut:
    return StudentOut(
        id=s.id,
        full_name=s.full_name,
        short_name=s.short_name,
        first_name=s.first_name,
        group_name=s.group_name,
        faculty=s.faculty,
        course=s.course,
        record_book_no=s.record_book_no,
        education_form=s.education_form,
        funding=s.funding,
        is_demo=is_demo(s),
    )


def template_out(t: RequestTemplate) -> TemplateOut:
    return TemplateOut(
        key=t.key,
        title=t.title,
        short_title=t.short_title or t.title,
        description=t.description,
        icon=t.icon,
        category=t.category,
        sla_days=max(1, round((t.sla_hours or 72) / 24)),
        produces_document=t.produces_document,
        auto_issue=bool(t.auto_issue),
        fields=t.fields,
    )


def document_out(d: Document) -> DocumentOut:
    base = settings.MINIAPP_PUBLIC_URL.rstrip("/")
    return DocumentOut(
        uuid=d.uuid,
        file_name=d.file_name,
        issued_by=d.issued_by,
        issued_at=d.issued_at,
        valid_until=d.valid_until,
        revoked=d.revoked_at is not None,
        download_url=f"{base}/api/documents/{d.uuid}",
        verify_url=f"{base}/verify/{d.uuid}",
    )


def request_out(r: Request, *, with_student: bool = False) -> RequestOut:
    return RequestOut(
        id=r.id,
        public_no=r.public_no,
        template_key=r.template_key,
        title=r.template.short_title or r.template.title,
        icon=r.template.icon,
        status=r.status,
        status_title=STATUS_TITLES.get(r.status, r.status),
        is_active=r.is_active,
        comment=r.comment,
        created_at=r.created_at,
        updated_at=r.updated_at,
        due_at=r.due_at,
        payload=r.payload_json or {},
        field_labels={
            f["name"]: f.get("label") or f["name"]
            for f in (r.template.fields or [])
            if isinstance(f, dict) and f.get("name")
        },
        events=[
            RequestEventOut(
                to_status=e.to_status,
                status_title=STATUS_TITLES.get(e.to_status, e.to_status),
                actor_name=e.actor_name,
                actor_kind=e.actor_kind,
                comment=e.comment,
                created_at=e.created_at,
            )
            for e in (r.events or [])
        ],
        document=document_out(r.document) if r.document else None,
        student_name=r.student.full_name if with_student and r.student else None,
        student_group=r.student.group_name if with_student and r.student else None,
    )


def event_out(e: CalendarEvent, taken: int = 0, my_status: str | None = None) -> EventOut:
    return EventOut(
        id=e.id,
        title=e.title,
        description=e.description,
        kind=e.kind,
        kind_title=EVENT_KIND_TITLES.get(e.kind, e.kind),
        starts_at=e.starts_at,
        ends_at=e.ends_at,
        location=e.location,
        organizer_name=e.organizer_name,
        cover_url=e.cover_url,
        capacity=e.capacity,
        taken=taken,
        registration_required=e.registration_required,
        my_status=my_status,
        details=e.details_json or {},
    )


def opportunity_out(
    o: Opportunity, my_interest: str | None = None, score: float = 0.0
) -> OpportunityOut:
    days_left = None
    if o.registration_deadline:
        delta = o.registration_deadline - datetime.now(timezone.utc)
        days_left = max(0, delta.days)
    return OpportunityOut(
        id=o.id,
        title=o.title,
        description=o.description,
        kind=o.kind,
        kind_title=OPP_KINDS.get(o.kind, o.kind),
        level=o.level,
        level_title=OPP_LEVELS.get(o.level, o.level),
        organizer=o.organizer,
        url=o.url,
        cover_url=o.cover_url,
        registration_deadline=o.registration_deadline,
        days_left=days_left,
        team_size_min=o.team_size_min,
        team_size_max=o.team_size_max,
        prize_text=o.prize_text,
        tags=list(o.tags or []),
        moderation_status=o.moderation_status,
        source=o.source,
        my_interest=my_interest,
        score=score,
        details=o.details_json or {},
    )


def intent_out(
    i: Intent, student: Student | None = None, score: float = 0.0
) -> IntentOut:
    return IntentOut(
        id=i.id,
        kind=i.kind,
        kind_title=INTENT_KINDS.get(i.kind, i.kind),
        title=i.title,
        description=i.description,
        tags=list(i.tags or []),
        author_name=(student.first_name if student else None) or i.author.display_name,
        author_photo=i.author.photo_url or "",
        author_course=student.course if student else None,
        author_faculty=student.faculty if student else None,
        opportunity_title=i.opportunity.title if i.opportunity else None,
        created_at=i.created_at,
        score=score,
    )
