"""Обработка апдейтов бота.

Роль бота в продукте — транспорт: точка входа в мини-приложение, доставка
уведомлений и файлов. Сложные диалоги ведёт приложение, а не чат.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AppUser, Binding, Student
from app.integrations.max.client import max_client, send_with_app_button

log = logging.getLogger("max.webhook")

# Дедупликация: повторная доставка апдейтов случается, а дубль справки — недопустим
_seen: dict[str, float] = {}
_SEEN_TTL = 600.0

# Слоган привязан к треку (решение 062): справка — крючок, но продукт — про старт
# первокурсника. Приветствие — гид на минуту: эксперт проходит главный сценарий
# «заявка ушла → PDF пришёл в этот чат», не читая README.
_ENTER_STEP = (
    "Нажми «Попробовать как студент (демо)» — личный демо-профиль, код не нужен."
    if settings.DEMO_MODE
    else "Введи код из деканата — он привяжет аккаунт к учётной записи студента."
)

WELCOME = (
    "Привет! Это «Кампус» — приложение для первокурсника: справка файлом в чат, "
    "ответы по регламентам вуза и свои люди рядом.\n\n"
    "Попробуй за минуту:\n"
    "1. Открой приложение кнопкой ниже.\n"
    f"2. {_ENTER_STEP}\n"
    "3. Закажи «Справку об обучении» — PDF придёт сюда, в этот чат."
)

ALREADY_BOUND = (
    "Всё под рукой в приложении: справки, расписание, ассистент и люди.\n\n"
    "Справка об обучении выдаётся сразу — PDF придёт сюда, в этот чат. "
    "Открывай кнопкой ниже."
)

HELP = (
    "«Кампус» — первокурснику: справка файлом в чат, ответы по регламентам, свои люди.\n\n"
    "В этот чат приходят статусы заявок, готовые справки PDF-файлом, напоминания "
    "о парах и событиях и отклики от других студентов.\n\n"
    "Заказать справку, спросить ассистента или найти напарника — в приложении, "
    "кнопка ниже."
)


def _seen_before(key: str) -> bool:
    now = time.monotonic()
    for k, ts in list(_seen.items()):
        if now - ts > _SEEN_TTL:
            _seen.pop(k, None)
    if key in _seen:
        return True
    _seen[key] = now
    return False


def _update_key(update: dict) -> str:
    for path in (
        ("message", "body", "mid"),
        ("callback", "callback_id"),
        ("message", "timestamp"),
    ):
        cur: object = update
        for part in path:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur:
            return f"{update.get('update_type', '?')}:{cur}"
    return f"{update.get('update_type', '?')}:{update.get('timestamp', time.time())}"


def _extract_user(update: dict) -> dict | None:
    if "callback" in update and isinstance(update["callback"], dict):
        user = update["callback"].get("user")
        if user:
            return user
    msg = update.get("message") or {}
    sender = msg.get("sender")
    if sender:
        return sender
    return update.get("user")


async def handle_update(session: AsyncSession, update: dict) -> None:
    if not settings.bot_enabled:
        return

    key = _update_key(update)
    if _seen_before(key):
        log.debug("Дубль апдейта, пропускаем: %s", key)
        return

    update_type = update.get("update_type") or update.get("type") or ""
    user = _extract_user(update)
    if not user:
        return

    max_user_id = user.get("user_id") or user.get("id")
    if not max_user_id:
        return

    await _touch_user(session, max_user_id, user)

    if update_type in ("bot_started", "bot_added"):
        await _send(max_user_id, WELCOME)
        return

    if update_type == "message_callback":
        callback = update.get("callback") or {}
        cb_id = callback.get("callback_id")
        payload = callback.get("payload") or ""
        if cb_id:
            try:
                await max_client.answer_callback(cb_id, notification="Открой приложение")
            except Exception:
                log.exception("Не удалось ответить на callback")
        log.info("Callback %s от %s", payload, max_user_id)
        return

    if update_type == "message_created":
        text = ((update.get("message") or {}).get("body") or {}).get("text") or ""
        await _handle_text(session, max_user_id, text.strip())
        return


async def _handle_text(session: AsyncSession, max_user_id: int, text: str) -> None:
    low = text.lower()

    if low in ("/start", "start", "начать", "/help", "help", "помощь"):
        bound = await _is_bound(session, max_user_id)
        if low in ("/help", "help", "помощь"):
            await _send(max_user_id, HELP)
        else:
            await _send(max_user_id, ALREADY_BOUND if bound else WELCOME)
        return

    # Любое другое сообщение — мягко возвращаем в приложение, где живёт ассистент
    await _send(
        max_user_id,
        "Ассистент живёт внутри приложения — там он видит твои заявки и расписание "
        "событий, поэтому отвечает точнее.\n\nОткрой и спроси там.",
    )


async def _send(max_user_id: int, text: str, label: str = "Открыть приложение") -> None:
    try:
        # send_with_app_button сам понижает кнопку до ссылки, а потом до текста:
        # пока организаторы не привязали мини-приложение к боту, запрос
        # с кнопкой open_app отклоняется целиком, и человек не получает ничего.
        await send_with_app_button(max_user_id, text, label)
    except Exception:
        log.exception("Не удалось отправить сообщение пользователю %s", max_user_id)


async def _touch_user(session: AsyncSession, max_user_id: int, user: dict) -> None:
    res = await session.execute(select(AppUser).where(AppUser.max_user_id == max_user_id))
    app_user = res.scalar_one_or_none()
    if app_user is None:
        session.add(
            AppUser(
                max_user_id=max_user_id,
                first_name=user.get("first_name") or user.get("name") or "",
                last_name=user.get("last_name") or "",
                username=user.get("username") or "",
                photo_url=user.get("avatar_url") or "",
            )
        )
        await session.flush()


async def _is_bound(session: AsyncSession, max_user_id: int) -> bool:
    res = await session.execute(
        select(Student.id)
        .join(Binding, Binding.student_id == Student.id)
        .join(AppUser, AppUser.id == Binding.app_user_id)
        .where(AppUser.max_user_id == max_user_id)
    )
    return res.scalar_one_or_none() is not None
