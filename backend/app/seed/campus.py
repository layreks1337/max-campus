"""Демо-данные учёбы: расписание групп, баллы БРС, корпуса, староста.

⚠️ Синтетика, как и весь сид. Адреса корпусов — публичные адреса ИГУ,
расписание и баллы выдуманы.
"""

from __future__ import annotations

import hashlib

# Сетка звонков: номер пары -> (начало, конец), местное время
BELLS = {
    1: ("08:00", "09:30"),
    2: ("09:50", "11:20"),
    3: ("11:40", "13:10"),
    4: ("13:50", "15:20"),
    5: ("15:40", "17:10"),
    6: ("17:20", "18:50"),
}

BUILDINGS = [
    {
        "code": "MAIN",
        "name": "Главный корпус",
        "address": "Иркутск, ул. Карла Маркса, 1",
        "hint": "Вход с улицы Карла Маркса, гардероб слева от турникетов. "
                "Ректорат и приёмная комиссия — второй этаж.",
        "floors": 4,
        "cover_url": "/covers/freshmen.jpg",
    },
    {
        "code": "IMIT",
        "name": "Корпус ИМИТ",
        "address": "Иркутск, бульвар Гагарина, 20",
        "hint": "Первая цифра номера аудитории — этаж: 412 — четвёртый этаж. "
                "Лифт справа от входа, компьютерные классы — третий этаж.",
        "floors": 5,
        "cover_url": "/covers/masterclass.jpg",
    },
    {
        "code": "LAW",
        "name": "Юридический институт",
        "address": "Иркутск, ул. Улан-Баторская, 10",
        "hint": "Библиотека института — первый этаж, читальный зал до 19:00.",
        "floors": 4,
        "cover_url": "",  # без фото: на снимке водяной знак другого вуза
    },
    {
        "code": "SPORT",
        "name": "Спорткомплекс",
        "address": "Иркутск, ул. Лермонтова, 124",
        "hint": "Сменная обувь обязательна. Раздевалки — цокольный этаж.",
        "floors": 2,
        "cover_url": "",  # без фото: на снимке американская команда
    },
]

# Предметы по факультетам: (предмет, вид, преподаватель, аудитория, корпус)
SUBJECTS = {
    "Институт математики и информационных технологий": [
        ("Математический анализ", "Лекция", "Горбунов В. А.", "412", "IMIT"),
        ("Математический анализ", "Практика", "Ершова Т. Н.", "305", "IMIT"),
        ("Алгебра и геометрия", "Лекция", "Кравцов П. С.", "412", "IMIT"),
        ("Программирование на Python", "Лаба", "Ильин Д. М.", "318", "IMIT"),
        ("Дискретная математика", "Практика", "Ершова Т. Н.", "306", "IMIT"),
        ("История России", "Лекция", "Белова Н. К.", "Актовый зал", "MAIN"),
        ("Английский язык", "Практика", "Смит О. В.", "214", "IMIT"),
        ("Физическая культура", "Практика", "Тарасов И. И.", "Зал 2", "SPORT"),
    ],
    "_default": [
        ("Введение в специальность", "Лекция", "Орлова Е. П.", "201", "MAIN"),
        ("История России", "Лекция", "Белова Н. К.", "Актовый зал", "MAIN"),
        ("Иностранный язык", "Практика", "Смит О. В.", "305", "MAIN"),
        ("Философия", "Семинар", "Лаптев А. Ю.", "210", "MAIN"),
        ("Информатика", "Лаба", "Ильин Д. М.", "318", "IMIT"),
        ("Физическая культура", "Практика", "Тарасов И. И.", "Зал 2", "SPORT"),
    ],
}

# Неделя: день -> список (номер пары, индекс предмета, чётность)
WEEK = {
    0: [(2, 0, "any"), (3, 1, "any"), (4, 6, "any")],
    1: [(1, 2, "any"), (2, 3, "any"), (3, 3, "odd")],
    2: [(2, 4, "any"), (3, 0, "any"), (5, 7, "any")],
    3: [(1, 5, "any"), (2, 2, "any"), (3, 1, "even")],
    4: [(2, 3, "any"), (3, 6, "any"), (4, 4, "odd")],
    5: [(2, 7, "any"), (3, 0, "even")],
}


def schedule_for(group_name: str, faculty: str) -> list[dict]:
    subjects = SUBJECTS.get(faculty, SUBJECTS["_default"])
    out = []
    for weekday, pairs in WEEK.items():
        for pair_no, idx, parity in pairs:
            subject, kind, teacher, room, building = subjects[idx % len(subjects)]
            starts, ends = BELLS[pair_no]
            out.append({
                "group_name": group_name,
                "weekday": weekday,
                "pair_no": pair_no,
                "starts": starts,
                "ends": ends,
                "subject": subject,
                "kind": kind,
                "teacher": teacher,
                "room": room,
                "building_code": building,
                "parity": parity,
            })
    return out


# Контрольные точки: (название, максимум)
CHECKPOINTS = [("Контрольная работа 1", 25), ("Домашние задания", 15), ("Работа на занятиях", 10)]


def _points(seed: str, maximum: int) -> int:
    """Детерминированные «баллы»: одинаковые при каждом пересоздании базы."""
    h = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
    return round(maximum * (0.55 + (h % 45) / 100))


def grades_for(record_book_no: str, faculty: str) -> list[dict]:
    subjects = SUBJECTS.get(faculty, SUBJECTS["_default"])
    seen: set[str] = set()
    out = []
    for subject, _kind, teacher, *_ in subjects:
        if subject in seen or subject == "Физическая культура":
            continue
        seen.add(subject)
        control = "Зачёт" if subject in ("История России", "Английский язык", "Иностранный язык") else "Экзамен"
        for title, maximum in CHECKPOINTS:
            out.append({
                "subject": subject,
                "title": title,
                "points": _points(f"{record_book_no}:{subject}:{title}", maximum),
                "max_points": maximum,
                "control": control,
                "teacher": teacher,
            })
    return out


# Староста Б-25-1 — основной демо-студент, чтобы сценарий старосты
# был виден эксперту без переключения аккаунтов.
GROUP_HEAD_RECORD_BOOK = "25101"
