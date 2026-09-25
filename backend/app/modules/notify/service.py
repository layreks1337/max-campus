"""Уведомления в чат MAX через таблицу outbox.

Прямых вызовов Bot API из HTTP-хендлеров нет и быть не должно: лимит 30 rps,
ретраи при «медиа ещё обрабатывается», выживание при рестарте — всё это решает очередь.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dates import UNIVERSITY_TZ
from app.db.models import OUT_FAILED, OUT_PENDING, OUT_SENT, Outbox, utcnow
from app.db.session import SessionLocal
from app.integrations.max.client import MaxApiError, max_client, send_with_app_button

log = logging.getLogger("notify")

MAX_ATTEMPTS = 6
QUIET_START_HOUR = 22
QUIET_END_HOUR = 8


async def enqueue(
    session: AsyncSession,
    *,
    max_user_id: int,
    kind: str,
    text: str,
    dedup_key: str,
    open_app_label: str | None = None,
    file_path: str | None = None,
    respect_quiet_hours: bool = False,
) -> Outbox | None:
    """Поставить сообщение в очередь. Повтор по dedup_key молча игнорируется.

    Синтетические пользователи не получают ничего: демо-соседи из сида имеют
    отрицательный max_user_id, тестовые аккаунты режима разработки лежат
    в диапазоне 900000–900999. Иначе бот стучится в несуществующие аккаунты
    и засоряет очередь бесконечными ретраями.
    """
    if not max_user_id or max_user_id <= 0:
        return None
    if settings.ALLOW_DEV_AUTH and 900_000 <= max_user_id <= 900_999:
        log.debug("Пропускаем уведомление тестовому пользователю %s", max_user_id)
        return None

    payload: dict = {}
    if open_app_label:
        payload["open_app_label"] = open_app_label
    if file_path:
        payload["file_path"] = file_path

    next_at = utcnow()
    if respect_quiet_hours:
        # Тихие часы — по времени студента, а не сервера: в UTC «22:00» — это
        # шесть утра в Иркутске, и ночные сообщения уходили бы ровно в ночь.
        local_now = next_at.astimezone(UNIVERSITY_TZ)
        hour = local_now.hour
        if hour >= QUIET_START_HOUR:
            next_at = (local_now + timedelta(days=1)).replace(
                hour=QUIET_END_HOUR, minute=5, second=0, microsecond=0
            )
        elif hour < QUIET_END_HOUR:
            next_at = local_now.replace(hour=QUIET_END_HOUR, minute=5, second=0, microsecond=0)

    item = Outbox(
        max_user_id=max_user_id,
        kind=kind,
        text=text,
        payload_json=payload,
        dedup_key=dedup_key[:160],
        next_attempt_at=next_at,
    )
    session.add(item)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        log.debug("Дубль уведомления, пропускаем: %s", dedup_key)
        return None
    return item


async def _deliver(item: Outbox) -> None:
    label = item.payload_json.get("open_app_label")
    file_path = item.payload_json.get("file_path")

    if file_path:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"файл документа пропал: {path}")
        await max_client.send_document(item.max_user_id, path, item.text)
        return

    # Кнопка сама понижается до ссылки и до текста — см. send_with_app_button
    await send_with_app_button(item.max_user_id, item.text, label)


async def process_batch(limit: int = 20) -> int:
    """Обработать порцию очереди. Возвращает количество отправленных."""
    if not settings.bot_enabled:
        return 0

    sent = 0
    async with SessionLocal() as session:
        res = await session.execute(
            select(Outbox)
            .where(Outbox.status == OUT_PENDING, Outbox.next_attempt_at <= utcnow())
            .order_by(Outbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        items = list(res.scalars())

        for item in items:
            try:
                await _deliver(item)
                item.status = OUT_SENT
                item.sent_at = utcnow()
                item.error = ""
                sent += 1
            except Exception as exc:
                # Ловим широко намеренно: сетевые ошибки httpx не наследуют OSError,
                # и без этого одно неудачное сообщение роняло всю пачку.
                item.attempts += 1
                item.error = str(exc)[:500]
                if item.attempts >= MAX_ATTEMPTS:
                    item.status = OUT_FAILED
                    log.error("Уведомление %s окончательно не доставлено: %s", item.id, exc)
                else:
                    delay = min(2 ** item.attempts, 300)
                    item.next_attempt_at = utcnow() + timedelta(seconds=delay)
                    log.warning(
                        "Уведомление %s не доставлено (попытка %s), повтор через %ss: %s",
                        item.id,
                        item.attempts,
                        delay,
                        exc,
                    )
        await session.commit()
    return sent


async def outbox_worker(interval: float = 3.0) -> None:
    """Фоновая задача. Стартует в lifespan приложения."""
    log.info("Воркер очереди уведомлений запущен")
    while True:
        try:
            n = await process_batch()
            if n:
                log.info("Отправлено уведомлений: %s", n)
        except asyncio.CancelledError:
            log.info("Воркер очереди остановлен")
            raise
        except Exception:
            log.exception("Сбой в воркере очереди")
        await asyncio.sleep(interval)
