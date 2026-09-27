#!/usr/bin/env python
"""Проверка качества ассистента: маршрутизация инструментов и заземление ответов.

Для каждого вопроса задан ожидаемый инструмент (или его отсутствие) и признаки
корректного ответа. Это не юнит-тест модели, а регрессия на поведение связки
«принудительный RAG + tool calling»: она ловит ровно те дефекты, которые уже
случались — уход в эскалацию вместо чтения данных, ответ «не знаю» при наличии
результата инструмента и утечку служебного JSON в текст.

Запуск:  python scripts/test_assistant.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
AUTH = "dev:900001:Anna"

# (вопрос, ожидаемый инструмент или None, обязательные подстроки, запрещённые подстроки)
CASES: list[tuple[str, str | None, list[str], list[str]]] = [
    (
        "Сколько дней делается справка об обучении?",
        None,
        ["3", "дн"],
        ["не знаю"],
    ),
    (
        "Кому положена социальная стипендия?",
        None,
        [],
        ["не знаю"],
    ),
    (
        "Что нужно для заселения в общежитие?",
        None,
        [],
        ["не знаю"],
    ),
    (
        "Где моя заявка на справку?",
        "get_my_requests",
        [],
        ["не знаю"],
    ),
    (
        "Какие справки я могу заказать?",
        "list_request_templates",
        [],
        ["не знаю"],
    ),
    (
        "Что интересного в вузе на этой неделе?",
        "list_events",
        [],
        [],
    ),
    (
        "Какие сейчас идут хакатоны и конкурсы?",
        "list_opportunities",
        [],
        ["не знаю"],
    ),
    (
        "Мне кто-нибудь ответил в разделе знакомств?",
        "get_my_matches",
        [],
        [],
    ),
    (
        "Хочу оформить справку в военкомат",
        None,
        [],
        [],
    ),
    (
        "Сколько стоит проезд на маршрутке в Иркутске?",
        None,
        [],
        [],
    ),
]

FORBIDDEN_ALWAYS = [
    "get_my_requests", "list_opportunities", "escalate_to_human", "list_events",
    "tool_call", "function", "{\"", "```json",
]


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
        method=method,
    )
    req.add_header("Authorization", f"MaxInitData {AUTH}")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw}


def ask(question: str) -> dict:
    status, res = call("POST", "/api/assistant/ask", {"question": question})
    if status == 200:
        return res
    return {"answer": "", "status": status, "error": json.dumps(res, ensure_ascii=False)}


def ensure_bound() -> None:
    """Регрессия идёт от лица привязанного студента, а reset_demo.sh (его
    запускают после смоука) снимает привязку. Тогда привязываем тем же кодом,
    что и смоук; код снова освободит следующий reset_demo.sh."""
    status, me = call("GET", "/api/me")
    if status == 200 and not me.get("is_bound"):
        status, res = call("POST", "/api/binding/claim", {"code": "A7K2-9M"})
        if status != 200:
            print(f"Не удалось привязать тестового студента кодом A7K2-9M: {status} {res}")
            sys.exit(2)
        print("Тестовый студент привязан кодом A7K2-9M — после прогона: bash scripts/reset_demo.sh\n")


passed = failed = 0
warnings: list[str] = []

print(f"Ассистент: {BASE}\n")
ensure_bound()

for question, expect_tool, must_have, must_not in CASES:
    print("─" * 66)
    print(f"В: {question}")
    res = ask(question)
    answer = (res.get("answer") or "").strip()
    tools = res.get("tools_used") or []
    sources = res.get("sources") or []
    actions = res.get("actions") or []

    print(f"О: {answer[:260]}")
    if res.get("status") == 429:
        # Лимит 20 вопросов за 10 минут (решение 060): смоук (4 вопроса) и этот
        # прогон (10) с одного тестового id укладываются, а второй подряд — нет.
        # Дальше все ответы будут 429 — это не регрессия ассистента, прогон прерываем.
        print("   ✗ лимит вопросов исчерпан — прогон прерван. Подожди 10 минут "
              "или обнули лимит перезапуском: docker compose restart app")
        sys.exit(2)
    if res.get("error"):
        print(f"   ошибка сервера: {res['error'][:260]}")
    if tools:
        print(f"   инструменты: {', '.join(tools)}")
    if sources:
        print(f"   источники: {', '.join(s['title'][:40] for s in sources)}")
    if actions:
        print(f"   кнопки: {', '.join(a.get('label', '?')[:30] for a in actions)}")

    ok = True
    low = answer.lower()

    if not answer:
        print("   ✗ пустой ответ")
        ok = False

    for leak in FORBIDDEN_ALWAYS:
        if leak.lower() in low:
            print(f"   ✗ в тексте ответа утекло служебное: {leak}")
            ok = False

    for token in must_have:
        if token.lower() not in low:
            print(f"   ✗ нет ожидаемого фрагмента: «{token}»")
            ok = False

    for token in must_not:
        if token.lower() in low:
            print(f"   ✗ присутствует нежелательное: «{token}»")
            ok = False

    if expect_tool and expect_tool not in tools:
        # не проваливаем: выбор инструмента вероятностный, но фиксируем
        warnings.append(f"«{question[:44]}» → ожидался {expect_tool}, вызвано: {tools or 'ничего'}")
        print(f"   ! ожидался инструмент {expect_tool}")

    if "escalate_to_human" in tools and expect_tool != "escalate_to_human":
        warnings.append(f"«{question[:44]}» → преждевременная эскалация")
        print("   ! преждевременная эскалация в деканат")

    if ok:
        passed += 1
        print("   ✓")
    else:
        failed += 1

print("─" * 66)
print(f"\nуспешно: {passed}, провалено: {failed}")
if warnings:
    print("\nзамечания по маршрутизации (не критично, но стоит видеть):")
    for w in warnings:
        print(f"  · {w}")
sys.exit(1 if failed else 0)
