"""Рекомендации возможностей — взвешенный скоринг, без машинного обучения.

Объясняется за пятнадцать секунд, не падает на пустых данных и не требует
обучающей выборки, которой на хакатоне взяться неоткуда.
"""

from __future__ import annotations

from datetime import timezone

from app.db.models import Opportunity, Student, utcnow

# Какой уровень уместен какому курсу
_LEVEL_FIT = {
    1: {"INTERNAL": 2.0, "CITY": 2.0, "REGIONAL": 1.0, "FEDERAL": 0.0, "INTERNATIONAL": -0.5},
    2: {"INTERNAL": 1.5, "CITY": 2.0, "REGIONAL": 1.5, "FEDERAL": 0.5, "INTERNATIONAL": 0.0},
    3: {"INTERNAL": 1.0, "CITY": 1.5, "REGIONAL": 2.0, "FEDERAL": 1.5, "INTERNATIONAL": 1.0},
    4: {"INTERNAL": 0.5, "CITY": 1.0, "REGIONAL": 1.5, "FEDERAL": 2.0, "INTERNATIONAL": 1.5},
}


def score_opportunity(
    opp: Opportunity,
    student: Student,
    *,
    student_tags: set[str] | None = None,
    peers_interested: int = 0,
) -> float:
    score = 0.0

    # Пересечение тегов с интересами студента
    if student_tags:
        overlap = len(set(opp.tags or []) & student_tags)
        score += 3.0 * overlap

    # Уровень по курсу
    fit = _LEVEL_FIT.get(min(student.course, 4), _LEVEL_FIT[4])
    score += fit.get(opp.level, 0.5)

    # Факультет
    if opp.faculties and student.faculty in opp.faculties:
        score += 1.0

    # Дедлайн: не завтра и не через полгода
    if opp.registration_deadline:
        days = (opp.registration_deadline - utcnow()).days
        if days < 0:
            score -= 5.0
        elif days <= 2:
            score += 0.5
        elif 3 <= days <= 30:
            score += 2.0
        elif days <= 60:
            score += 0.5
    else:
        score += 0.2

    # Социальный сигнал: однокурсники уже отметились
    score += min(peers_interested, 3) * 1.0

    # Свежесть
    age_days = (utcnow() - opp.created_at.replace(tzinfo=timezone.utc)).days if opp.created_at else 0
    score -= min(age_days / 30.0, 1.0)

    return round(score, 2)
