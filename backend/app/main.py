"""Точка входа MAX Campus.

Бэкенд обслуживает и API, и собранный фронтенд: одно происхождение,
один HTTPS-адрес, никакого CORS. Для мини-приложения внутри мессенджера
это заметно проще в эксплуатации.
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import (
    routes_assistant,
    routes_campus,
    routes_core,
    routes_feed,
    routes_match,
    routes_public,
    routes_requests,
)
from app.core.config import settings
from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.seed import index_knowledge_if_needed, run_seed
from app.workers.scheduler import start_background_tasks

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("app")


class _HideLinkToken(logging.Filter):
    """Журнал доступа uvicorn пишет путь вместе с параметрами, а `?lt=` из
    ссылки бота — это вход в аккаунт на сутки (решение 057). Значение вырезаем."""

    _re = re.compile(r"([?&]lt=)[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._re.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args
            )
        return True


# uvicorn настраивает свои логгеры до импорта приложения — фильтр доживёт до запросов
logging.getLogger("uvicorn.access").addFilter(_HideLinkToken())

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


async def _prepare_database() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # create_all создаёт только новые таблицы, колонки в существующие не
        # добавляет. Миграций в проекте нет — точечные ALTER идемпотентны.
        for table in ("calendar_event", "opportunity"):
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS details_json JSONB NOT NULL DEFAULT '{{}}'"
            ))
        await conn.execute(text(
            "ALTER TABLE request_template ADD COLUMN IF NOT EXISTS auto_issue BOOLEAN NOT NULL DEFAULT FALSE"
        ))
    log.info("Схема БД готова")


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks: list[asyncio.Task] = []
    try:
        await _prepare_database()

        async with SessionLocal() as session:
            stats = await run_seed(session)
            log.info("Данные: %s", stats)

        # Индексация базы знаний может занять время — не держим старт приложения
        async def _index() -> None:
            async with SessionLocal() as session:
                try:
                    await index_knowledge_if_needed(session)
                except Exception:
                    log.exception("Индексация базы знаний не удалась")

        tasks.append(asyncio.create_task(_index(), name="kb-index"))
        tasks.extend(start_background_tasks())

        log.info(
            "%s запущен · бот: %s · ассистент: %s · публичный адрес: %s",
            settings.APP_NAME,
            "да" if settings.bot_enabled else "нет",
            "да" if settings.llm_enabled else "нет",
            settings.MINIAPP_PUBLIC_URL,
        )
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        from app.integrations.max.client import max_client
        from app.modules.assistant.llm import close_llm

        await max_client.aclose()
        await close_llm()
        await engine.dispose()
        log.info("Остановлено")


app = FastAPI(
    title="MAX Campus API",
    description=(
        "Кампус — первокурснику, внутри мессенджера MAX: справка файлом в чат, "
        "ответы по регламентам (ассистент на базе RAG), свои люди. Плюс заявления, "
        "расписание, календарь вуза, конкурсы и хакатоны."
    ),
    version="1.0.0",
    lifespan=lifespan,
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)


# ── Единый формат ошибок ──────────────────────────────────────────


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_FAILED",
                "message": "Проверьте параметры запроса",
                "details": {"errors": exc.errors()[:10]},
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    log.exception("Необработанная ошибка на %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL", "message": "Внутренняя ошибка сервера"}},
    )


from fastapi import HTTPException  # noqa: E402


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        return JSONResponse(status_code=exc.status_code, content={"error": detail})
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "HTTP_ERROR", "message": str(detail)}},
    )


# ── Роуты ─────────────────────────────────────────────────────────

app.include_router(routes_public.router)
app.include_router(routes_core.router, prefix="/api")
app.include_router(routes_requests.router, prefix="/api")
app.include_router(routes_requests.staff_router, prefix="/api")
app.include_router(routes_feed.events_router, prefix="/api")
app.include_router(routes_feed.opps_router, prefix="/api")
app.include_router(routes_feed.moderation_router, prefix="/api")
app.include_router(routes_match.router, prefix="/api")
app.include_router(routes_assistant.router, prefix="/api")
app.include_router(routes_campus.router, prefix="/api")
app.include_router(routes_campus.public_router)


# ── Раздача собранного фронтенда ──────────────────────────────────

if FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """Любой неизвестный путь отдаём SPA — роутинг на клиенте."""
        if full_path.startswith(("api/", "webhook/")):
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "NOT_FOUND", "message": "Метод не найден"}},
            )
        # resolve + проверка родителя: иначе `..%2F..%2Fetc%2Fpasswd` выходит из папки сборки
        dist = FRONTEND_DIST.resolve()
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_relative_to(dist) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

else:

    @app.get("/", include_in_schema=False)
    async def no_frontend():
        return JSONResponse(
            {
                "app": settings.APP_NAME,
                "note": "Фронтенд не собран. Выполните: cd frontend && npm install && npm run build",
                "api_docs": "/api/docs",
            }
        )
