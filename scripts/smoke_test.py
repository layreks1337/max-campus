#!/usr/bin/env python
"""Сквозная проверка основного пользовательского сценария.

Проходит путь, который на защите показывают вживую:
студент привязывается -> подаёт справку -> деканат принимает, подписывает
и выдаёт -> студенту уходит PDF -> документ проверяется по QR.
Плюс ассистент, календарь, возможности, матчинг, базовые проверки безопасности
и демо-вход экспертов: своя копия студента, роль деканата в один тап, своя очередь.
В конце — вход по подписанной ссылке из бота (?lt=…): секрет берётся из LINK_SECRET
или выводится из MAX_BOT_TOKEN — из окружения или из .env в корне репозитория.

Запуск:  python scripts/smoke_test.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")

# Имена латиницей намеренно: dev-токен уезжает в HTTP-заголовок Authorization,
# а заголовки допускают только latin-1. Настоящее ФИО приходит из справочника
# студентов после привязки, так что на продукт это не влияет.
STUDENT = "dev:900001:Anna"      # привяжем к коду A7K2-9M (Петрова Анна)
CLERK = "dev:900002:Irina"       # сотрудник деканата
HEAD = "dev:900003:Sergey"       # подписант
DEMO_EXPERT_NAME = "Smoke Expert"
DEMO_EXPERT = f"dev:900050:{DEMO_EXPERT_NAME}"  # демо-вход без кода, своя копия студента

passed = 0
failed = 0
notes: list[str] = []


def call(
    method: str,
    path: str,
    auth: str,
    body: dict | None = None,
    expect: tuple[int, ...] = (200, 201),
    scheme: str = "MaxInitData",
) -> tuple[int, object]:
    url = f"{BASE}{path}"
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"{scheme} {auth}")
    if data:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def check(title: str, condition: bool, detail: str = "") -> bool:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [ OK ] {title}")
    else:
        failed += 1
        print(f"  [FAIL] {title}" + (f" — {detail}" if detail else ""))
    return condition


def section(title: str) -> None:
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")


# ══════════════════════════════════════════════════════════════════

section("1. Здоровье сервиса")
status, health = call("GET", "/api/health", STUDENT)
check("health отвечает 200", status == 200, str(health))
if isinstance(health, dict):
    print(f"       бот: {health['features']['bot']}, ассистент: {health['features']['assistant']}")

section("2. Онбординг и привязка студенческого")
status, me = call("GET", "/api/me", STUDENT)
check("профиль доступен", status == 200, str(me))

if isinstance(me, dict) and not me.get("is_bound"):
    status, res = call("POST", "/api/requests", STUDENT, {"template_key": "study_certificate", "payload": {}})
    check("без привязки заявка запрещена (409)", status == 409, f"получили {status}")

    status, me = call("POST", "/api/binding/claim", STUDENT, {"code": "A7K2-9M"})
    check("привязка по коду прошла", status == 200, str(me))
else:
    check("студент уже привязан", True)

if isinstance(me, dict) and me.get("student"):
    s = me["student"]
    print(f"       {s['full_name']} · {s['group_name']} · {s['course']} курс · {s['faculty']}")

# Проверяем отдельным непривязанным пользователем: у уже привязанного
# эндпоинт корректно возвращает профиль и до проверки кода не доходит.
status, res = call("POST", "/api/binding/claim", "dev:900009:Probe", {"code": "ZZZZ-00"})
check("неверный код отклоняется", status in (404, 429), f"получили {status}")

section("3. Шаблоны заявок (движок на JSON)")
status, templates = call("GET", "/api/requests/templates", STUDENT)
check("список шаблонов получен", status == 200 and isinstance(templates, list))
if isinstance(templates, list):
    check("шаблонов не меньше 8", len(templates) >= 8, f"их {len(templates)}")
    for t in templates[:4]:
        print(f"       {t['icon']} {t['short_title']} — {t['sla_days']} дн., полей: {len(t['fields'])}")

status, tpl = call("GET", "/api/requests/templates/study_certificate", STUDENT)
check("схема полей отдаётся", status == 200 and bool(tpl.get("fields")))

section("4. Подача заявки и валидация формы")
status, res = call(
    "POST", "/api/requests", STUDENT,
    {"template_key": "study_certificate", "payload": {"copies": 99}},
)
check("пустое обязательное поле отклонено (422)", status == 422, f"получили {status}")
if status == 422 and isinstance(res, dict):
    details = res.get("error", {}).get("details", {})
    print(f"       ошибки полей: {details}")

status, req = call(
    "POST", "/api/requests", STUDENT,
    {
        "template_key": "study_certificate",
        "payload": {
            "purpose": "В органы соцзащиты",
            "copies": 2,
            "need_original": True,
            "comment": "Нужна для оформления социальной стипендии",
        },
    },
)
check("заявка создана", status in (200, 201), str(req))
public_no = req.get("public_no") if isinstance(req, dict) else None
if public_no:
    print(f"       №{public_no} · статус: {req['status_title']} · срок до {req.get('due_at', '')[:10]}")

section("5. Роль деканата")
status, staff_me = call("POST", "/api/binding/staff", CLERK, {"code": "STAFF-001"})
check("роль специалиста активирована", status == 200, str(staff_me))
status, head_me = call("POST", "/api/binding/staff", HEAD, {"code": "STAFF-002"})
check("роль подписанта активирована", status == 200, str(head_me))

status, res = call("GET", "/api/staff/requests", STUDENT)
check("студента в очередь деканата не пускает (403)", status == 403, f"получили {status}")

status, queue = call("GET", "/api/staff/requests", CLERK)
check("очередь заявок доступна сотруднику", status == 200 and isinstance(queue, list))
if isinstance(queue, list):
    print(f"       заявок в очереди: {len(queue)}")

section("6. Машина состояний")
status, res = call(
    "POST", f"/api/staff/requests/{public_no}/transition", CLERK,
    {"to_status": "ISSUED", "comment": "срезать угол"},
)
check("недопустимый переход блокируется (409)", status == 409, f"получили {status}")
if status == 409:
    print(f"       {res['error']['message']}")

status, res = call(
    "POST", f"/api/staff/requests/{public_no}/transition", CLERK,
    {"to_status": "IN_REVIEW", "comment": "Документы в порядке"},
)
check("переход в «Принята в работу»", status == 200, str(res))

status, res = call(
    "POST", f"/api/staff/requests/{public_no}/transition", HEAD,
    {"to_status": "SIGNING", "comment": "Передано на подпись"},
)
check("переход в «На подписи»", status == 200, str(res))

section("7. Выдача документа и PDF")
status, issued = call("POST", f"/api/staff/requests/{public_no}/issue", HEAD)
check("документ выдан", status == 200, str(issued))

doc = issued.get("document") if isinstance(issued, dict) else None
check("карточка документа появилась", bool(doc), "document пустой")
if doc:
    print(f"       файл: {doc['file_name']}")
    print(f"       uuid: {doc['uuid']}")
    try:
        with urllib.request.urlopen(f"{BASE}/api/documents/{doc['uuid']}", timeout=60) as r:
            content = r.read()
        check("PDF скачивается", content[:4] == b"%PDF", f"первые байты: {content[:8]!r}")
        check("PDF не пустой", len(content) > 3000, f"{len(content)} байт")
        print(f"       размер: {len(content)} байт")
    except Exception as exc:  # noqa: BLE001
        check("PDF скачивается", False, str(exc))

    status, verify = call("GET", f"/api/verify/{doc['uuid']}", STUDENT)
    check("проверка подлинности: найден", status == 200 and verify.get("found"))
    check("проверка подлинности: действителен", bool(verify.get("valid")), str(verify))
    if verify.get("found"):
        print(f"       выдан: {verify['student_name']} ({verify['student_group']})")
        print(f"       кем: {verify['issued_by']}")

    try:
        with urllib.request.urlopen(f"{BASE}/verify/{doc['uuid']}", timeout=30) as r:
            page = r.read().decode("utf-8")
        check("HTML-страница проверки открывается", "Проверка подлинности" in page)
    except Exception as exc:  # noqa: BLE001
        check("HTML-страница проверки открывается", False, str(exc))

status, mine = call("GET", f"/api/requests/{public_no}", STUDENT)
check("студент видит свою заявку", status == 200)
if isinstance(mine, dict):
    print(f"       статус: {mine['status_title']}, событий в истории: {len(mine['events'])}")
    check("история переходов полная", len(mine["events"]) >= 5, f"{len(mine['events'])} событий")
    for ev in mine["events"]:
        who = ev["actor_name"] or "система"
        print(f"         · {ev['status_title']:24} {who}")

section("8. Очередь уведомлений")
status, home = call("GET", "/api/home", STUDENT)
check("главный экран собирается", status == 200, str(home)[:200])
if isinstance(home, dict):
    print(f"       {home['greeting']}")
    print(f"       активных заявок: {len(home['active_requests'])}, "
          f"событий: {len(home['upcoming_events'])}, "
          f"рекомендаций: {len(home['recommended'])}, "
          f"колода: {home['deck_size']}")

section("9. Календарь вуза")
status, events = call("GET", "/api/events", STUDENT)
check("календарь отдаётся", status == 200 and isinstance(events, list))
if isinstance(events, list) and events:
    print(f"       событий для этого студента: {len(events)}")
    for e in events[:3]:
        print(f"       · {e['starts_at'][:16].replace('T', ' ')} {e['title'][:44]}")
    target = next((e for e in events if e["registration_required"]), None)
    if target:
        status, reg = call("POST", f"/api/events/{target['id']}/register", STUDENT)
        check("запись на событие", status == 200, str(reg))
        if isinstance(reg, dict):
            print(f"       статус записи: {reg['my_status']}, занято {reg['taken']}/{reg['capacity']}")
        status, reg2 = call("POST", f"/api/events/{target['id']}/register", STUDENT)
        check("повторная запись не дублируется", status == 200 and reg2["my_status"] == reg["my_status"])
    # Тестовому id бот ничего не шлёт — проверяется только ссылка
    status, share = call("POST", f"/api/events/{events[0]['id']}/share", STUDENT)
    check("«Поделиться»: диплинк max.ru/<бот>?startapp=event_<id>",
          status == 200 and isinstance(share, dict)
          and f"?startapp=event_{events[0]['id']}" in share.get("link", ""),
          str(share)[:200])

section("10. Возможности и рекомендации")
status, opps = call("GET", "/api/opportunities", STUDENT)
check("лента возможностей отдаётся", status == 200 and isinstance(opps, list))
if isinstance(opps, list) and opps:
    print(f"       возможностей: {len(opps)} (отсортированы по релевантности)")
    for o in opps[:3]:
        dl = f"дедлайн через {o['days_left']} дн." if o["days_left"] is not None else "без дедлайна"
        print(f"       · [{o['score']:5.2f}] {o['title'][:42]} — {dl}")
    check("скоринг расставил приоритеты", opps[0]["score"] >= opps[-1]["score"])

    first = opps[0]
    status, res = call("POST", f"/api/opportunities/{first['id']}/interest", STUDENT, {"level": "INTERESTED"})
    check("интерес отмечается", status == 200)

    status, intent = call(
        "POST", f"/api/opportunities/{first['id']}/looking-for-team", STUDENT,
        {"message": "Беру на себя бэкенд, ищу фронтендера"},
    )
    check("«ищу команду» создаёт объявление в колоде", status in (200, 201), str(intent))
    if isinstance(intent, dict):
        print(f"       создано объявление: {intent['title'][:52]}")

section("11. Матчинг")
status, deck = call("GET", "/api/match/deck", STUDENT)
check("колода не пустая", status == 200 and isinstance(deck, list) and len(deck) > 0,
      f"карточек: {len(deck) if isinstance(deck, list) else '—'}")
if isinstance(deck, list) and deck:
    print(f"       карточек в колоде: {len(deck)}")
    for card in deck[:3]:
        print(f"       · [{card['score']:5.2f}] {card['kind_title']:22} {card['title'][:38]}")
    status, sw = call("POST", "/api/match/swipe", STUDENT,
                      {"intent_id": deck[0]["id"], "decision": "LIKE"})
    check("свайп принимается", status == 200, str(sw))
    status, sw2 = call("POST", "/api/match/swipe", STUDENT,
                       {"intent_id": deck[0]["id"], "decision": "LIKE"})
    check("повторный свайп не дублируется", status == 200, f"{status} {sw2}")

    status, deck2 = call("GET", "/api/match/deck", STUDENT)
    check("свайпнутая карточка ушла из колоды",
          status == 200 and all(c["id"] != deck[0]["id"] for c in deck2),
          "карточка вернулась в колоду")

status, prof = call("PUT", "/api/match/profile", STUDENT,
                    {"bio": "Первый курс, рада знакомству",
                     "tags": ["ИМИТ", "первый курс", "математика"],
                     "district": "Центр", "wants_mentor": True,
                     "wants_mentee": False, "visible": True})
check("профиль знакомств сохраняется", status == 200, str(prof))

status, matches = call("GET", "/api/match/matches", STUDENT)
check("список откликов доступен", status == 200 and isinstance(matches, list))
if isinstance(matches, list):
    print(f"       откликов: {len(matches)}")
    for m in matches[:3]:
        print(f"       · {m['origin']:6} {m['partner_name']} — {m['about'][:34]}")

section("12. Ассистент (RAG + инструменты)")
status, st = call("GET", "/api/assistant/status", STUDENT)
llm_on = bool(st.get("enabled")) if isinstance(st, dict) else False
print(f"       ассистент включён: {llm_on}")

if llm_on:
    questions = [
        ("Сколько дней делается справка об обучении?", "регламент"),
        ("Где моя заявка?", "инструмент"),
        ("Какие есть хакатоны?", "инструмент"),
        ("Какая погода завтра в Москве?", "вне базы знаний"),
    ]
    for question, kind in questions:
        status, ans = call("POST", "/api/assistant/ask", STUDENT, {"question": question})
        ok = status == 200 and isinstance(ans, dict) and bool(ans.get("answer"))
        check(f"ответ на «{question[:38]}» ({kind})", ok, str(ans)[:200])
        if ok:
            print(f"       → {ans['answer'][:170]}")
            if ans.get("tools_used"):
                print(f"         инструменты: {', '.join(ans['tools_used'])}")
            if ans.get("sources"):
                print(f"         источники: {', '.join(s['title'][:34] for s in ans['sources'][:2])}")
            if ans.get("actions"):
                print(f"         кнопки: {', '.join(a.get('label','?')[:28] for a in ans['actions'][:2])}")
            print()
else:
    notes.append("Ассистент выключен — не заданы YC_API_KEY/YC_FOLDER_ID")

section("13. Безопасность")


def raw_get(path: str) -> tuple[int, str]:
    """GET без нормализации пути клиентом — как `curl --path-as-is`.

    urllib и браузеры схлопывают `..` ещё до отправки, а атакующий шлёт путь
    как есть. http.client передаёт строку запроса побайтно.
    """
    parts = urllib.parse.urlsplit(BASE)
    conn_cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parts.hostname, parts.port, timeout=30)
    try:
        conn.request("GET", parts.path.rstrip("/") + path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", "replace")
    finally:
        conn.close()


try:
    status, page = raw_get("/..%2F..%2F..%2Fetc%2Fpasswd")
    check(
        "обход папки сборки отдаёт index.html, а не /etc/passwd",
        status == 200 and 'id="root"' in page and "root:x:" not in page,
        f"{status}: {page[:80]!r}",
    )
except Exception as exc:  # noqa: BLE001
    check("обход папки сборки отдаёт index.html, а не /etc/passwd", False, str(exc))

status, res = call("GET", "/api/me", "dev:12345:X")
check("dev-вход с нетестовым id отклоняется (401)", status == 401, f"получили {status}")

# Случайный секрет заведомо не совпадёт с настоящим. Тело без пользователя —
# даже если сервер его примет, обрабатывать нечего.
fake = urllib.request.Request(
    f"{BASE}/webhook/max",
    data=json.dumps({"update_type": "smoke_test"}).encode(),
    method="POST",
    headers={"Content-Type": "application/json", "X-Max-Bot-Api-Secret": secrets.token_hex(16)},
)
try:
    with urllib.request.urlopen(fake, timeout=30) as resp:
        status = resp.status
except urllib.error.HTTPError as exc:
    status = exc.code
check("вебхук с чужим секретом отклоняется (403)", status == 403,
      f"получили {status} — задан ли MAX_WEBHOOK_SECRET?")

section("14. Демо-вход для экспертов")
# Свой id и имя: копия называется по профилю MAX. Id фиксированный — повторный
# прогон получает ту же копию, а reset_demo.sh её удаляет.
status, dme = call("POST", "/api/binding/demo", DEMO_EXPERT)
check("демо-вход без кода создаёт профиль", status == 200 and isinstance(dme, dict)
      and bool(dme.get("is_bound")), f"{status} {str(dme)[:200]}")
ds = (dme.get("student") or {}) if isinstance(dme, dict) else {}
check("копия помечена как демо (зачётка DEMO-…)",
      ds.get("is_demo") is True and str(ds.get("record_book_no", "")).startswith("DEMO-"), str(ds))
check("ФИО копии — из профиля MAX", ds.get("full_name") == DEMO_EXPERT_NAME, str(ds.get("full_name")))
if ds:
    print(f"       {ds.get('full_name')} · {ds.get('group_name')} · зачётка {ds.get('record_book_no')}")

status, again = call("POST", "/api/binding/demo", DEMO_EXPERT)
check("повторный демо-вход возвращает ту же копию",
      status == 200 and isinstance(again, dict) and ds.get("id") is not None
      and (again.get("student") or {}).get("id") == ds.get("id"))

status, dgrades = call("GET", "/api/grades", DEMO_EXPERT)
check("баллы шаблона скопированы",
      status == 200 and isinstance(dgrades, dict) and len(dgrades.get("subjects", [])) > 0, str(dgrades)[:160])

status_demo, dgroup = call("GET", "/api/group", DEMO_EXPERT)
status_real, rgroup = call("GET", "/api/group", STUDENT)
check("копия — староста своей группы (экран опросов)",
      status_demo == 200 and isinstance(dgroup, dict) and dgroup.get("is_head") and dgroup.get("demo"),
      str(dgroup)[:200])
if status_demo == 200 and status_real == 200:
    check("демо-копии не раздувают счётчик группы",
          dgroup["members"] == rgroup["members"] + 1,
          f"у демо {dgroup['members']}, у студента {rgroup['members']}")
    check("для группы староста — по-прежнему оригинал", not rgroup.get("demo") and bool(rgroup.get("head_name"))
          and rgroup["head_name"] != DEMO_EXPERT_NAME, str(rgroup.get("head_name")))

status, dreq = call(
    "POST", "/api/requests", DEMO_EXPERT,
    {"template_key": "study_certificate",
     "payload": {"purpose": "По месту требования", "copies": 1, "need_original": False}},
)
check("демо-студент подаёт заявку", status in (200, 201), str(dreq)[:200])
demo_no = dreq.get("public_no") if isinstance(dreq, dict) else None
# Если справку выдаёт автомат, заявка сразу ISSUED — смотрим её среди выданных
demo_auto = isinstance(dreq, dict) and dreq.get("status") == "ISSUED"

status, res = call("POST", "/api/binding/demo-staff", STUDENT)
check("роль деканата в один тап — только демо-профилю (403)", status == 403, f"получили {status}")

status, dean = call("POST", "/api/binding/demo-staff", DEMO_EXPERT)
check("роль деканата в один тап, без кода",
      status == 200 and isinstance(dean, dict) and dean.get("role") == "STAFF_HEAD", str(dean)[:200])

status, dqueue = call("GET", "/api/staff/requests" + ("?status=ISSUED" if demo_auto else ""), DEMO_EXPERT)
check("в очереди демо-деканата своя заявка и только свои",
      status == 200 and isinstance(dqueue, list) and any(r["public_no"] == demo_no for r in dqueue)
      and all(r.get("student_name") == DEMO_EXPERT_NAME for r in dqueue),
      str([(r["public_no"], r.get("student_name")) for r in dqueue])[:200] if isinstance(dqueue, list) else str(dqueue))

if public_no:
    status, res = call(
        "POST", f"/api/staff/requests/{public_no}/transition", DEMO_EXPERT,
        {"to_status": "IN_REVIEW", "comment": ""},
    )
    check("чужую заявку демо-деканат не видит (404)", status == 404, f"получили {status}")

if demo_auto:
    check("демо-студент получил справку", bool(dreq.get("document")), str(dreq)[:200])
elif demo_no:
    for to in ("IN_REVIEW", "SIGNING"):
        status, res = call("POST", f"/api/staff/requests/{demo_no}/transition", DEMO_EXPERT,
                           {"to_status": to, "comment": ""})
    status, dissued = call("POST", f"/api/staff/requests/{demo_no}/issue", DEMO_EXPERT)
    check("демо-деканат выдаёт свою справку",
          status == 200 and isinstance(dissued, dict) and bool(dissued.get("document")), str(dissued)[:200])

section("15. Вход по подписанной ссылке из бота")


def env_value(key: str) -> str:
    """Переменная из окружения, иначе из .env в корне репозитория."""
    if os.environ.get(key):
        return os.environ[key]
    env_file = Path(__file__).resolve().parents[1] / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == key:
                return value.strip().strip("\"'")
    except OSError:
        pass
    return ""


def link_token(user_id: int, exp: int, secret: bytes) -> str:
    """Тот же формат, что выдаёт бот (security.make_link_token): <id>.<exp>.<hex HMAC>.
    Своя реализация намеренно — сверяет сервер с описанным форматом."""
    sig = hmac.new(secret, f"{user_id}.{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{exp}.{sig}"


link_secret = env_value("LINK_SECRET").encode()
if not link_secret and env_value("MAX_BOT_TOKEN"):
    link_secret = hmac.new(b"CampusLinkToken", env_value("MAX_BOT_TOKEN").encode(), hashlib.sha256).digest()

if not link_secret:
    notes.append("Вход по ссылке не проверен — нет LINK_SECRET/MAX_BOT_TOKEN ни в окружении, ни в .env")
else:
    LINK_USER = 900070  # тестовый id: уведомления ему не уходят
    valid = link_token(LINK_USER, int(time.time()) + 3600, link_secret)
    status, lme = call("GET", "/api/me", valid, scheme="MaxLink")
    check("подписанная ссылка пускает, id — из токена",
          status == 200 and isinstance(lme, dict) and lme.get("max_user_id") == LINK_USER,
          f"{status} {str(lme)[:160]} — совпадает ли секрет с сервером?")

    # Настоящий (не тестовый) id: dev-вход его не пускает, ссылка бота — да.
    # Только чтение профиля, уведомлений этому id ничего не ставит в очередь.
    status, rme = call("GET", "/api/me", link_token(12345, int(time.time()) + 3600, link_secret),
                       scheme="MaxLink")
    check("ссылка пускает и нетестовый id, закрытый для dev-входа",
          status == 200 and isinstance(rme, dict) and rme.get("max_user_id") == 12345, f"получили {status}")

    uid, exp, sig = valid.split(".")
    forged_sig = f"{uid}.{exp}.{sig[:-1]}{'0' if sig[-1] != '0' else '1'}"
    status, _ = call("GET", "/api/me", forged_sig, scheme="MaxLink")
    check("ссылка с подделанной подписью отклоняется (401)", status == 401, f"получили {status}")

    status, _ = call("GET", "/api/me", f"{LINK_USER + 1}.{exp}.{sig}", scheme="MaxLink")
    check("ссылка с чужим id под той же подписью отклоняется (401)", status == 401, f"получили {status}")

    expired = link_token(LINK_USER, int(time.time()) - 60, link_secret)
    status, res = call("GET", "/api/me", expired, scheme="MaxLink")
    check("просроченная ссылка отклоняется (401)", status == 401, f"получили {status}")

    status, _ = call("GET", "/api/me", "not-a-token", scheme="MaxLink")
    check("мусор вместо токена ссылки — 401, а не 500", status == 401, f"получили {status}")

section("ИТОГ")
print(f"  успешно: {passed}")
print(f"  провалено: {failed}")
for note in notes:
    print(f"  ! {note}")
print()
sys.exit(1 if failed else 0)
