#!/usr/bin/env python
"""Выгрузка тестовых данных в testdata/*.json — из модулей сида, а не руками.

Кейс (с. 10) просит для собственного API тестовые данные в JSON или CSV, нужные
для воспроизводимой проверки. Всё здесь синтетическое (FAQ, пп. 13, 15) и берётся
из того же кода, которым сид наполняет базу (backend/app/seed), поэтому файлы
не расходятся с тем, что получает проверяющий:

    students.json           студенты справочника, шаблон демо-входа и его баллы
    groups.json             группы: институт, курс, состав, староста, пары в неделю
    request_templates.json  виды заявок и справок: поля форм, срок, автовыдача
    binding_codes.json      коды привязки студентов и сотрудников — что даёт каждый
    roles.json              тестовые роли и как войти каждой; прогон DATA-API
    knowledge_base.json     документы базы знаний ассистента (заголовки)
    events.json             демо-события афиши; даты — «через N дней» от сегодня

Использование:
    python scripts/export_testdata.py            записать testdata/
    python scripts/export_testdata.py --check    файлы совпадают с сидом?

Нужны зависимости бэкенда (backend/.venv). Если их нет, данные собираются
в контейнере campus-app — из кода последней сборки образа. Код выхода: 0 — готово
(или файлы актуальны), 1 — не удалось собрать (или файлы устарели).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    ROOT = Path(__file__).resolve().parents[1]
except NameError:  # запуск из stdin внутри контейнера: python - --bundle
    ROOT = None
CONTAINER = "campus-app"

SYNTHETIC = (
    "Синтетические данные для проверки: люди, коды, события и тексты выдуманы, "
    "совпадения с реальными людьми случайны. Реальные системы вуза не подключены — "
    "см. README, «Что смоделировано»."
)
GENERATED = "Сгенерировано scripts/export_testdata.py из {src}. Руками не править."


def _header(src: str) -> dict:
    return {"synthetic": True, "note": SYNTHETIC, "generated": GENERATED.format(src=src)}


def build() -> dict[str, dict]:
    """Все файлы testdata: имя -> содержимое. Требует пакет app в sys.path."""
    from app.core.config import TEST_USER_ID_MAX, TEST_USER_ID_MIN, settings
    from app.core.dates import UNIVERSITY_TZ
    from app.core.deps import ISSUER_ROLES, REQUEST_ROLES
    from app.db.models import STAFF_ROLES, utcnow
    from app.modules.demo.service import DEMO_PREFIX, DEMO_STAFF_CODE
    from app.seed import campus, demo, knowledge, templates

    codes_by_idx = {idx: code for code, idx in demo.BINDING_CODES}
    template_row = next(r for r in demo.STUDENTS if r[6] == demo.DEMO_TEMPLATE_RECORD_BOOK)
    tz = f"UTC{settings.UNIVERSITY_TZ_HOURS:+d}"

    # ── Студенты ───────────────────────────────────────────────────
    students = []
    for i, row in enumerate(demo.STUDENTS):
        last, first, middle, group, faculty, course, book, birth, form, funding = row
        if i < demo.REAL_USER_SLOTS:
            account = {
                "type": "binding_code",
                "binding_code": codes_by_idx.get(i),
                "note": "Вход по одноразовому коду привязки (POST /api/binding/claim)",
            }
        else:
            account = {
                "type": "demo-seed",
                "max_user_id": -(1000 + i),
                "username": f"demo_{book}",
                "note": "Синтетический сосед по кампусу: аккаунт с отрицательным id, "
                        "войти под ним нельзя; автор объявлений «Людей»",
            }
        students.append({
            "full_name": " ".join(p for p in (last, first, middle) if p),
            "last_name": last,
            "first_name": first,
            "middle_name": middle,
            "group_name": group,
            "faculty": faculty,
            "faculty_short": demo.FAC_SHORT[faculty],
            "course": course,
            "record_book_no": book,
            "birth_date": birth,
            "education_form": form,
            "funding": funding,
            # Так же, как seed_students
            "enrolled_year": 2026 - course + 1,
            "is_demo_template": book == demo.DEMO_TEMPLATE_RECORD_BOOK,
            "is_group_head": book == campus.GROUP_HEAD_RECORD_BOOK,
            "grades_count": len(campus.grades_for(book, faculty)),
            "account": account,
        })

    students_file = {
        **_header("backend/app/seed/demo.py (STUDENTS) и seed/campus.py (баллы, староста)"),
        "demo_template": {
            "record_book_no": demo.DEMO_TEMPLATE_RECORD_BOOK,
            "full_name": " ".join(template_row[:3]),
            "group_name": template_row[3],
            "how_used": "POST /api/binding/demo («Попробовать как студент (демо)») создаёт "
                        "аккаунту свою копию этого студента: группа, курс, институт, баллы "
                        "и права старосты те же, зачётка "
                        f"{DEMO_PREFIX}<id аккаунта в базе>, ФИО — из профиля MAX (нет имени — "
                        "ФИО шаблона). Копия одна на аккаунт; scripts/reset_demo.sh удаляет копии.",
            "grades": campus.grades_for(demo.DEMO_TEMPLATE_RECORD_BOOK, template_row[4]),
        },
        "students": students,
    }

    # ── Группы ─────────────────────────────────────────────────────
    groups: dict[tuple[str, str], dict] = {}
    for s in students:
        g = groups.setdefault((s["group_name"], s["faculty"]), {
            "group_name": s["group_name"],
            "faculty": s["faculty"],
            "faculty_short": s["faculty_short"],
            "course": s["course"],
            "students": [],
            "group_head": None,
            "schedule_slots": len(campus.schedule_for(s["group_name"], s["faculty"])),
        })
        g["students"].append(s["record_book_no"])
        if s["is_group_head"]:
            g["group_head"] = s["record_book_no"]
    groups_file = {
        **_header("backend/app/seed/demo.py и seed/campus.py"),
        "note_schedule": "Расписание синтетическое (seed/campus.py, schedule_for): schedule_slots — "
                         "строк расписания группы на неделю, включая пары только чётной или "
                         "нечётной недели.",
        "groups": [groups[k] for k in sorted(groups)],
    }

    # ── Шаблоны заявок ─────────────────────────────────────────────
    request_templates = []
    for t in templates.TEMPLATES:
        request_templates.append({
            "key": t["key"],
            "title": t["title"],
            "short_title": t.get("short_title", ""),
            "category": t.get("category", ""),
            "description": t.get("description", ""),
            "sla_hours": t.get("sla_hours"),
            # Так же, как serializers.template_out
            "sla_days": max(1, round((t.get("sla_hours") or 72) / 24)),
            "produces_document": t.get("produces_document", False),
            "auto_issue": t.get("auto_issue", False),
            "fields": t.get("schema_json", {}).get("fields", []),
        })
    templates_file = {
        **_header("backend/app/seed/templates.py (TEMPLATES)"),
        "api": "GET /api/requests/templates, GET /api/requests/templates/{key}; "
               "подача — POST /api/requests {\"template_key\": ..., \"payload\": {<name поля>: значение}}",
        "auto_issue_rule": "auto_issue=true — типовой документ выдаётся в том же запросе "
                           "(«Демо-деканат (автоматическая выдача)»). Заполненное поле с "
                           "manual_review=true делает заявку нетиповой: она идёт в очередь деканата.",
        "templates": request_templates,
    }

    # ── Коды привязки ──────────────────────────────────────────────
    by_book = {s["record_book_no"]: s for s in students}
    student_codes = []
    for code, idx in demo.BINDING_CODES:
        s = by_book[demo.STUDENTS[idx][6]]
        grants = "Роль STUDENT: аккаунт привязывается к этому студенту справочника"
        if s["is_group_head"]:
            grants += "; студент — староста группы (опросы группы)"
        student_codes.append({
            "code": code,
            "student": s["full_name"],
            "record_book_no": s["record_book_no"],
            "group_name": s["group_name"],
            "course": s["course"],
            "grants": grants,
        })

    def staff_grants(role: str) -> list[str]:
        out = []
        if role in REQUEST_ROLES:
            out.append("очередь заявок деканата: принять в работу, запросить уточнение, "
                       "отклонить, передать на подпись")
        if role in ISSUER_ROLES:
            out.append("подпись («Готова») и выдача документа — PDF уходит студенту")
        if role in STAFF_ROLES:
            out.append("проверка билетов на входе (код или QR)")
        return out

    staff_codes = [
        {
            "code": code,
            "role": role,
            "full_name": name,
            "department": dept,
            "position": position,
            "grants": staff_grants(role),
        }
        for name, dept, role, position, code in demo.STAFF
    ]
    demo_staff_role = next(role for _n, _d, role, _p, code in demo.STAFF if code == DEMO_STAFF_CODE)
    codes_file = {
        **_header("backend/app/seed/demo.py (BINDING_CODES, STAFF)"),
        "student_codes": {
            "api": "POST /api/binding/claim {\"code\": \"A7K2-9M\"}",
            "rules": "Код одноразовый: студент привязывается к одному аккаунту. "
                     "scripts/reset_demo.sh снимает привязки и освобождает коды. "
                     "Подбор ограничен: 5 попыток в час на аккаунт и 20 неудачных с адреса.",
            "codes": student_codes,
        },
        "staff_codes": {
            "api": "POST /api/binding/staff {\"code\": \"STAFF-001\"}",
            "rules": "Код многоразовый: роль получает любой аккаунт, который его ввёл. Коды "
                     "опубликованы, поэтому в очереди по коду — только синтетические студенты "
                     "справочника, заявок демо-копий экспертов там нет. Публиковать события и "
                     "модерировать на демо-стенде нельзя никому — 403 DEMO_READ_ONLY.",
            "codes": staff_codes,
        },
        "demo_login": [
            {
                "api": "POST /api/binding/demo",
                "grants": "Роль STUDENT: своя копия шаблонного студента "
                          f"{demo.DEMO_TEMPLATE_RECORD_BOOK}, код не нужен",
            },
            {
                "api": "POST /api/binding/demo-staff",
                "grants": f"Роль {demo_staff_role} — как по коду {DEMO_STAFF_CODE}, только "
                          "аккаунту с демо-копией; в очереди — только заявки своей копии",
            },
        ],
    }

    # ── Роли и вход ────────────────────────────────────────────────
    dev_example = "MaxInitData dev:990301:Expert"
    roles_file = {
        **_header("backend/app/core (вход и роли) и seed/demo.py"),
        "test_accounts": {
            "header": "Authorization: MaxInitData dev:<id>:<Имя>",
            "id_range": [TEST_USER_ID_MIN, TEST_USER_ID_MAX],
            "rules": [
                "Тестовый вход без подписи MAX — только для id из диапазона, иначе 401 "
                "BAD_INIT_DATA; выключается переменной ALLOW_DEV_AUTH=false.",
                "Аккаунт создаётся при первом запросе; новый id — чистый аккаунт.",
                "Для повторных прогонов берите тот же id: новых демо-копий для тестовых "
                "id — не больше 10 в час с одного адреса и 120 в час на сервер, сверх "
                "лимита POST /api/binding/demo — 429 RATE_LIMITED.",
                "Имя — латиницей: заголовки HTTP допускают только latin-1.",
                "Сообщения в MAX тестовым id не отправляются: PDF — по ссылке из заявки.",
                "scripts/reset_demo.sh удаляет тестовые аккаунты вместе со всем, что они создали.",
            ],
            "password": None,
        },
        "roles": [
            {
                "role": "public",
                "how": "Без заголовка Authorization",
                "can": "GET /api/health; PDF и проверка подлинности по uuid документа "
                       "(GET /api/documents/{doc_uuid}, GET /api/verify/{doc_uuid}, "
                       "страница /verify/{doc_uuid}) — так открывается QR-код из справки",
            },
            {
                "role": "student",
                "how": f"Authorization: {dev_example} → POST /api/binding/demo "
                       "(своя копия демо-студента) или POST /api/binding/claim с кодом студента",
                "can": "Профиль, заявки и справки, ассистент, афиша и билеты, «Люди» — "
                       "только свои данные",
            },
            {
                "role": f"{demo_staff_role} (демо, в один тап)",
                "how": "Тот же аккаунт с демо-копией → POST /api/binding/demo-staff",
                "can": "Очередь деканата со своими заявками: провести заявку до выдачи PDF, "
                       "проверить билет",
            },
            *(
                {
                    "role": c["role"],
                    "how": f"Отдельный тестовый id → POST /api/binding/staff {{\"code\": \"{c['code']}\"}}",
                    "can": "; ".join(c["grants"]),
                }
                for c in staff_codes
            ),
        ],
        "in_max": "В MAX вход — подписанная строка запуска (Authorization: MaxInitData <initData>, "
                  "HMAC-SHA256 от токена бота, живёт час). В браузере по кнопке бота — "
                  "Authorization: MaxLink <токен из ?lt=>, сутки. Логинов и паролей в сервисе нет.",
        "data_api": {
            "file": "DATA-API.yaml",
            "role_student_token_env": "DATA_API_TOKEN_STUDENT",
            "role_student_token_example": dev_example,
            "run": f"DATA_API_TOKEN_STUDENT=\"{dev_example}\" python scripts/check_data_api.py",
            "cleanup": "bash scripts/reset_demo.sh",
        },
    }

    # ── База знаний ────────────────────────────────────────────────
    kb_file = {
        **_header("backend/app/seed/knowledge.py (DOCUMENTS)"),
        "note_content": "Тексты составлены по типовым нормам российских вузов и не являются "
                        "актами ИГУ; в базе помечены is_demo=true.",
        "documents": [
            {"title": d["title"], "source_type": d["source_type"], "chars": len(d["body"])}
            for d in knowledge.DOCUMENTS
        ],
    }

    # ── События ────────────────────────────────────────────────────
    today = utcnow().astimezone(UNIVERSITY_TZ).date()

    def when(dt):
        if dt is None:
            return None
        local = dt.astimezone(UNIVERSITY_TZ)
        return {"in_days": (local.date() - today).days, "local_time": local.strftime("%H:%M")}

    events = []
    for e in demo._events():
        events.append({
            "title": e["title"],
            "kind": e["kind"],
            "starts": when(e["starts_at"]),
            "ends": when(e.get("ends_at")),
            "location": e["location"],
            "organizer_name": e["organizer_name"],
            "audience": e.get("audience_json", {}),
            "capacity": e.get("capacity", 0),
            "registration_required": e.get("registration_required", False),
            "description": e["description"],
        })
    events_file = {
        **_header("backend/app/seed/demo.py (events)"),
        "note_dates": "Даты сдвигаются от текущего дня при каждом старте и раз в сутки: "
                      f"in_days — через сколько дней от сегодня, local_time — время вуза ({tz}). "
                      "capacity 0 — без ограничения мест; билет (QR) — у событий с записью.",
        "api": "GET /api/events; запись — POST /api/events/{event_id}/register, "
               "билет — GET /api/events/{event_id}/ticket",
        "events": events,
    }

    return {
        "students.json": students_file,
        "groups.json": groups_file,
        "request_templates.json": templates_file,
        "binding_codes.json": codes_file,
        "roles.json": roles_file,
        "knowledge_base.json": kb_file,
        "events.json": events_file,
    }


def build_here_or_in_container() -> tuple[dict[str, dict], str]:
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        import app.seed  # noqa: F401 — проверка, что зависимости бэкенда есть
    except ImportError as exc:
        print(f"Зависимостей бэкенда нет ({exc.name}) — собираю в контейнере {CONTAINER}",
              file=sys.stderr)
        proc = subprocess.run(
            ["docker", "exec", "-i", CONTAINER, "python", "-", "--bundle"],
            input=Path(__file__).read_text(encoding="utf-8"),
            capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip()[-600:] or "docker exec завершился с ошибкой") from None
        return json.loads(proc.stdout), f"контейнер {CONTAINER}"
    return build(), "модули сида"


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Выгрузка testdata/*.json из сида")
    ap.add_argument("--out", help="каталог (по умолчанию testdata/ в корне репозитория)")
    ap.add_argument("--check", action="store_true",
                    help="не записывать, а сверить с файлами: код выхода 1, если они устарели")
    ap.add_argument("--bundle", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.bundle:  # внутри контейнера: всё одним JSON в stdout
        print(json.dumps(build(), ensure_ascii=False))
        return 0

    try:
        files, source = build_here_or_in_container()
    except Exception as exc:  # docker, импорт сида
        print(f"Тестовые данные не собраны: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else ROOT / "testdata"
    stale = []
    for name, data in files.items():
        path = out / name
        text = render(data)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
            continue
        out.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"  {path}")

    if args.check:
        if stale:
            print(f"Устарели ({source}): {', '.join(stale)} — перегенерируйте без --check")
            return 1
        print(f"testdata актуальны — {len(files)} файлов ({source})")
        return 0
    print(f"Готово: {len(files)} файлов в {out} ({source})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
