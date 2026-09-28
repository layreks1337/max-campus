"""Форматирование дат по-русски.

Почему отдельный модуль: на Windows `strftime` кодирует строку формата
системной локалью, и кириллица прямо в шаблоне (`"%d.%m в %H:%M"`) валится с
UnicodeEncodeError. Поэтому в strftime уходят только ASCII-шаблоны,
а русские слова приклеиваются обычной конкатенацией.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import settings

# Смещение из UNIVERSITY_TZ_HOURS, по умолчанию Иркутск, UTC+8. Фиксированное
# смещение, а не ZoneInfo: в slim-образе может не оказаться базы часовых поясов,
# а в России переходов на летнее время нет.
UNIVERSITY_TZ = timezone(timedelta(hours=settings.UNIVERSITY_TZ_HOURS))


def local(dt: datetime) -> datetime:
    """Время вуза. Всё, что видит человек, показывается по времени вуза."""
    return dt.astimezone(UNIVERSITY_TZ) if dt.tzinfo else dt

MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

MONTHS_NOM = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def date_ru(dt: datetime) -> str:
    """23 сентября 2026"""
    return f"{dt.day} {MONTHS_GEN[dt.month - 1]} {dt.year}"


def date_short(dt: datetime) -> str:
    """23.09.2026"""
    return dt.strftime("%d.%m.%Y")


def when_ru(dt: datetime) -> str:
    """23.09 в 17:00 — основной формат для уведомлений о событиях."""
    dt = local(dt)
    return f"{dt.strftime('%d.%m')} в {dt.strftime('%H:%M')}"


def when_full_ru(dt: datetime) -> str:
    """23 сентября в 17:00"""
    dt = local(dt)
    return f"{dt.day} {MONTHS_GEN[dt.month - 1]} в {dt.strftime('%H:%M')}"


def weekday_ru(dt: datetime) -> str:
    return WEEKDAYS[dt.weekday()]
