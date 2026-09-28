"""Обработка апдейтов бота.

Роль бота в продукте — транспорт: точка входа в мини-приложение, доставка
уведомлений и файлов. Сложные диалоги ведёт приложение, а не чат.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import is_test_user_id, settings
from app.core.limits import SlidingWindow
from app.db.models import AppUser, Binding, Student
from app.integrations.max.client import max_client, send_with_app_button

log = logging.getLogger("max.webhook")

# Дедупликация: повторная доставка апдейтов случается, а дубль справки — недопустим
_seen: dict[str, float] = {}
_SEEN_TTL = 600.0

# Апдейт без подтверждённого секрета мог прислать кто угодно, вписав чужой id
# (решение 077). Таких — не больше 30 в минуту на всех, а ответов одному адресату —
# не больше 5 за 10 минут: чужой скрипт не разошлёт приветствия от имени бота, не
# наплодит пользователей и не займёт ограничитель запросов к MAX, через который
# идут справки в чат. Апдейты с верным секретом прислал MAX — их не ограничиваем.
_unverified_updates = SlidingWindow(30, 60)
_unverified_replies = SlidingWindow(5, 600)

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


async def handle_update(session: AsyncSession, update: dict, verified: bool = False) -> None:
    """Обработать апдейт. `verified` — пришёл с верным секретом, то есть от MAX.

    Сначала всё, что нужно из базы, потом коммит и только после него запросы к
    MAX: соединение с базой не держится, пока ответ ждёт общий ограничитель
    скорости. Иначе поток апдейтов занимал бы весь пул, и вставали бы остальные
    запросы к API.
    """
    if not settings.bot_enabled:
        return
    if not verified and not _unverified_updates.take("all"):
        log.warning("Апдейтов без подтверждённого секрета больше 30 в минуту — пропускаем")
        return

    key = _update_key(update)
    if _seen_before(key):
        log.debug("Дубль апдейта, пропускаем: %s", key)
        return

    update_type = update.get("update_type") or update.get("type") or ""
    user = _extract_user(update)
    if not isinstance(user, dict):
        return

    max_user_id = user.get("user_id") or user.get("id")
    if not isinstance(max_user_id, int) or isinstance(max_user_id, bool) or max_user_id <= 0:
        return

    await _touch_user(session, max_user_id, user, trusted=verified)

    reply: str | None = None
    callback_id: str | None = None
    if update_type in ("bot_started", "bot_added"):
        reply = WELCOME
    elif update_type == "message_callback":
        callback = update.get("callback") or {}
        callback_id = callback.get("callback_id") or None
        log.info("Callback %s от %s", callback.get("payload") or "", max_user_id)
    elif update_type == "message_created":
        text = ((update.get("message") or {}).get("body") or {}).get("text") or ""
        reply = await _reply_to_text(session, max_user_id, str(text).strip())

    await session.commit()

    if reply is None and callback_id is None:
        return
    if settings.ALLOW_DEV_AUTH and is_test_user_id(max_user_id):
        # Как и в очереди уведомлений: таких аккаунтов в MAX нет
        log.debug("Ответ тестовому пользователю %s не отправляем", max_user_id)
        return
    if not verified and not _unverified_replies.take(max_user_id):
        log.warning("Ответов пользователю %s без подтверждённого секрета больше 5 за 10 минут — "
                    "пропускаем", max_user_id)
        return

    if callback_id:
        try:
            await max_client.answer_callback(callback_id, notification="Открой приложение")
        except Exception:
            log.exception("Не удалось ответить на callback")
    if reply:
        await _send(max_user_id, reply)


async def _reply_to_text(session: AsyncSession, max_user_id: int, text: str) -> str:
    low = text.lower()

    if low in ("/help", "help", "помощь"):
        return HELP
    if low in ("/start", "start", "начать"):
        return ALREADY_BOUND if await _is_bound(session, max_user_id) else WELCOME

    # Любое другое сообщение — мягко возвращаем в приложение, где живёт ассистент
    return (
        "Ассистент живёт внутри приложения — там он видит твои заявки и расписание "
        "событий, поэтому отвечает точнее.\n\nОткрой и спроси там."
    )


async def _send(max_user_id: int, text: str, label: str = "Открыть приложение") -> None:
    try:
        # send_with_app_button сам понижает кнопку до ссылки, а потом до текста:
        # пока организаторы не привязали мини-приложение к боту, запрос
        # с кнопкой open_app отклоняется целиком, и человек не получает ничего.
        await send_with_app_button(max_user_id, text, label)
    except Exception:
        log.exception("Не удалось отправить сообщение пользователю %s", max_user_id)


async def _touch_user(session: AsyncSession, max_user_id: int, user: dict, trusted: bool = False) -> None:
    first_name = str(user.get("first_name") or user.get("name") or "")[:80]
    last_name = str(user.get("last_name") or "")[:80]
    username = str(user.get("username") or "")[:80]
    photo_url = str(user.get("avatar_url") or "")[:1000]

    res = await session.execute(select(AppUser).where(AppUser.max_user_id == max_user_id))
    app_user = res.scalar_one_or_none()
    if app_user is None:
        session.add(
            AppUser(
                max_user_id=max_user_id,
                first_name=first_name,
                last_name=last_name,
                username=username,
                photo_url=photo_url,
            )
        )
        await session.flush()
    elif trusted and first_name:
        # Имя из апдейта с верным секретом — из профиля MAX. Переписываем: запись
        # мог создать поддельный апдейт до подтверждения секрета, а по ней вход по
        # ссылке бота называет демо-копию и печатает имя в PDF.
        app_user.first_name = first_name
        app_user.last_name = last_name
        if username:
            app_user.username = username
        if photo_url:
            app_user.photo_url = photo_url


async def _is_bound(session: AsyncSession, max_user_id: int) -> bool:
    res = await session.execute(
        select(Student.id)
        .join(Binding, Binding.student_id == Student.id)
        .join(AppUser, AppUser.id == Binding.app_user_id)
        .where(AppUser.max_user_id == max_user_id)
    )
    return res.scalar_one_or_none() is not None
