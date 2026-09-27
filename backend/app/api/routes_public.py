"""Публичные endpoint'ы: здоровье, скачивание и проверка документа, вебхук бота."""

from __future__ import annotations

import hmac
import logging
from html import escape
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request as HttpRequest, Response
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select

from app.api.schemas import VerifyOut
from app.core.config import settings
from app.core.deps import SessionDep
from app.db.models import Document, Request, utcnow

log = logging.getLogger("api.public")
router = APIRouter(tags=["public"])

MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _ru_date(dt) -> str:
    return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}"


@router.get("/api/health", summary="Проверка живости")
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.ENV,
        "features": {
            "bot": settings.bot_enabled,
            "assistant": settings.llm_enabled,
        },
    }


@router.get("/api/documents/{doc_uuid}", summary="Скачать документ")
async def download_document(doc_uuid: str, session: SessionDep) -> FileResponse:
    res = await session.execute(select(Document).where(Document.uuid == doc_uuid))
    doc = res.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Документ не найден"})
    path = Path(doc.file_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail={"code": "GONE", "message": "Файл недоступен"})
    return FileResponse(path, media_type="application/pdf", filename=doc.file_name)


@router.get("/api/verify/{doc_uuid}", response_model=VerifyOut, summary="Проверка подлинности (JSON)")
async def verify_json(doc_uuid: str, session: SessionDep) -> VerifyOut:
    res = await session.execute(select(Document).where(Document.uuid == doc_uuid))
    doc = res.scalar_one_or_none()
    if doc is None:
        return VerifyOut(found=False, valid=False, reason="Документ с таким кодом не выдавался")

    req = await session.get(Request, doc.request_id)
    valid, reason = True, ""
    if doc.revoked_at is not None:
        valid, reason = False, "Документ отозван"
    elif doc.valid_until and doc.valid_until < utcnow():
        valid, reason = False, "Срок действия истёк"

    return VerifyOut(
        found=True,
        valid=valid,
        reason=reason,
        document_title=req.template.title if req else None,
        number=req.public_no if req else None,
        student_name=req.student.full_name if req else None,
        student_group=req.student.group_name if req else None,
        issued_by=doc.issued_by,
        issued_at=doc.issued_at,
        valid_until=doc.valid_until,
    )


@router.get("/verify/{doc_uuid}", response_class=HTMLResponse, summary="Страница проверки")
async def verify_page(doc_uuid: str, session: SessionDep) -> HTMLResponse:
    data = await verify_json(doc_uuid, session)

    if not data.found:
        badge = '<div class="badge bad">Не найден</div>'
        body = (
            '<p class="muted">Документа с таким кодом в системе нет. '
            "Проверьте, что QR-код отсканирован полностью.</p>"
        )
    else:
        if data.valid:
            badge = '<div class="badge ok">Документ действителен</div>'
        else:
            badge = f'<div class="badge bad">{escape(data.reason)}</div>'
        rows = [
            ("Документ", data.document_title),
            ("Номер", data.number),
            ("Выдан", data.student_name),
            ("Группа", data.student_group),
            ("Кем выдан", data.issued_by),
            ("Дата выдачи", _ru_date(data.issued_at) if data.issued_at else None),
            ("Действителен до", _ru_date(data.valid_until) if data.valid_until else None),
        ]
        body = '<dl class="rows">' + "".join(
            f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>"
            for k, v in rows
            if v
        ) + "</dl>"

    html = f"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Проверка документа · MAX Campus</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 24px; background: #ffffff; color: #141414;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  .card {{
    width: 100%; max-width: 480px; background: #fff;
    border: 1px solid #f0f0f0; border-radius: 24px; padding: 32px;
  }}
  h1 {{ font-size: 24px; line-height: 1.25; margin: 0 0 4px; font-weight: 650; }}
  .sub {{ color: #707070; font-size: 14px; margin: 0 0 24px; }}
  .badge {{
    display: inline-block; border-radius: 999px; padding: 8px 16px;
    font-size: 13px; font-weight: 600; margin-bottom: 24px;
  }}
  .badge.ok {{ background: #e8f7ee; color: #1f7a45; }}
  .badge.bad {{ background: #fdeceb; color: #b3261e; }}
  .rows {{ margin: 0; display: grid; grid-template-columns: 1fr; gap: 0; }}
  dt {{ font-size: 12px; color: #adadad; margin-top: 16px; }}
  dd {{ margin: 2px 0 0; font-size: 16px; }}
  .note {{
    margin-top: 28px; padding-top: 20px; border-top: 1px solid #f0f0f0;
    font-size: 12px; line-height: 1.5; color: #adadad;
  }}
  .muted {{ color: #707070; font-size: 15px; line-height: 1.5; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0e0e0f; color: #f3f3f4; }}
    .card {{ background: #1c1c1f; border-color: rgba(255,255,255,.08); }}
    dt {{ color: #6e6e73; }}
    .note {{ border-color: rgba(255,255,255,.08); color: #6e6e73; }}
    .muted {{ color: #a1a1a6; }}
    .badge.ok {{ background: rgba(53,192,122,.14); color: #35c07a; }}
    .badge.bad {{ background: rgba(255,107,94,.14); color: #ff6b5e; }}
  }}
</style></head>
<body><main class="card">
  <h1>Проверка подлинности</h1>
  <p class="sub">Кампус · справки вуза в мессенджере MAX</p>
  {badge}
  {body}
  <p class="note">
    Документ сформирован сервисом MAX Campus. Усиленная квалифицированная электронная
    подпись не применялась — эта страница подтверждает только факт выдачи документа
    через сервис и его текущий статус.
  </p>
</main></body></html>"""
    return HTMLResponse(html)


# ── Вебхук бота ───────────────────────────────────────────────────

_seen_updates: dict[str, float] = {}

# Один раз за процесс: пишем в лог, пришёл ли у первого вебхука заголовок секрета
# (сам секрет не пишем никогда), и предупреждаем про вебхуки без него. По этой
# строке решается, можно ли включать MAX_WEBHOOK_REQUIRE_SECRET.
_webhook_header_logged = False
_webhook_no_secret_warned = False


def _check_webhook_secret(request: HttpRequest) -> bool:
    """Пропускать ли вебхук. Неверный секрет — всегда нет; без секрета — по флагу.

    Только заголовок: секрет в строке запроса осел бы в журнале доступа.
    """
    global _webhook_header_logged, _webhook_no_secret_warned

    header = request.headers.get("X-Max-Bot-Api-Secret")
    expected = settings.MAX_WEBHOOK_SECRET
    if header and expected and not hmac.compare_digest(header.encode(), expected.encode()):
        # Такой запрос прислал не MAX (подделка или смоук-тест после выкладки),
        # поэтому он не занимает «первый вебхук» в логе ниже.
        log.warning("Вебхук с неверным секретом отклонён")
        return False

    if not _webhook_header_logged:
        _webhook_header_logged = True
        log.info(
            "Первый вебхук после старта: заголовок X-Max-Bot-Api-Secret %s",
            "есть" if header else "отсутствует",
        )

    if header or not expected:
        return True
    if settings.MAX_WEBHOOK_REQUIRE_SECRET:
        log.warning("Вебхук без заголовка секрета отклонён")
        return False
    if not _webhook_no_secret_warned:
        _webhook_no_secret_warned = True
        log.warning(
            "вебхук без заголовка секрета — принят, потому что MAX_WEBHOOK_REQUIRE_SECRET=false"
        )
    return True


@router.post("/webhook/max", summary="Вебхук Bot API")
async def max_webhook(request: HttpRequest, session: SessionDep) -> dict:
    """Отвечаем 200 всегда и быстро: иначе таймаут -> ретрай -> дубли у пользователя.

    Исключение — запрос не прошёл проверку секрета: это не MAX, а подделка,
    ей 403 и никакой обработки.
    """
    if not _check_webhook_secret(request):
        raise HTTPException(
            status_code=403,
            detail={"code": "BAD_WEBHOOK_SECRET", "message": "Неверный секрет вебхука"},
        )

    try:
        body = await request.json()
    except Exception:
        return {"ok": True}

    try:
        from app.integrations.max.webhook import handle_update

        await handle_update(session, body)
    except Exception:
        # ошибка обработки не должна давать 5xx — MAX будет ретраить вечно
        log.exception("Ошибка обработки апдейта")
    return {"ok": True}


@router.get("/webhook/max", summary="Проверка вебхука")
async def max_webhook_probe() -> Response:
    return Response(status_code=200)
