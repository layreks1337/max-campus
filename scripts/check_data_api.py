#!/usr/bin/env python
"""Прогон сценария DATA-API.yaml против живого API — так, как это сделает проверка жюри.

Официальный валидатор (gitverse.ru/stasnorman/example-data-api) проверяет только
структуру файла. Этот скрипт выполняет сами запросы: по порядку, с зависимостями
dependsOn, переменными из extract, проверкой кодов, типа содержимого, обязательных
полей и bodySchema, а в конце — шаги cleanup.

Использование:
    DATA_API_TOKEN_STUDENT="MaxInitData dev:990001:Expert" \\
        python scripts/check_data_api.py [DATA-API.yaml] [--base-url URL]

Токен роли берётся из переменной DATA_API_TOKEN_<РОЛЬ> и уходит в заголовок
Authorization. Роль public ходит без авторизации. Код выхода: 0 — все проверки
прошли, 1 — есть провалы, 2 — не удалось прочитать файл.

Нужен PyYAML; bodySchema проверяется, если установлен jsonschema. Прогон создаёт
тестовому аккаунту демо-копию студента, справку и роль деканата — локально их
убирает bash scripts/reset_demo.sh.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

try:
    from jsonschema import Draft202012Validator
except ImportError:  # bodySchema тогда не проверяется, остальное работает
    Draft202012Validator = None

VAR = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


def substitute(value, variables: dict):
    if isinstance(value, str):
        return VAR.sub(lambda m: str(variables.get(m.group(1), m.group(0))), value)
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    return value


def json_path(data, expr: str):
    """Минимальный JSONPath: $.a.b, $[0].a, $.a[1].b — ровно то, что нужно для extract."""
    if not expr.startswith("$"):
        raise ValueError(f"выражение должно начинаться с $: {expr}")
    cur = data
    for key, idx in re.findall(r"\.([A-Za-z0-9_]+)|\[(\d+)\]", expr[1:]):
        if key:
            cur = cur[key]
        else:
            cur = cur[int(idx)]
    return cur


def has_field(data, dotted: str) -> bool:
    try:
        json_path(data, "$." + dotted if not dotted.startswith("[") else "$" + dotted)
        return True
    except (KeyError, IndexError, TypeError):
        return False


def call(base: str, step: dict, variables: dict, default_headers: dict, tokens: dict):
    req = substitute(step.get("request") or {}, variables)
    path = step["path"]
    for name, val in (req.get("path") or {}).items():
        path = path.replace("{" + name + "}", urllib.parse.quote(str(val), safe=""))
    url = base.rstrip("/") + path
    if req.get("query"):
        url += "?" + urllib.parse.urlencode(req["query"])

    headers = dict(default_headers)
    headers.update(req.get("headers") or {})
    role = step.get("role", "public")
    if role != "public":
        token = tokens.get(role)
        if not token:
            raise RuntimeError(f"нет токена для роли {role}: задайте DATA_API_TOKEN_{role.upper()}")
        headers["Authorization"] = token

    body = None
    if "body" in req and req["body"] is not None:
        body = json.dumps(req["body"], ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json; charset=utf-8")

    r = urllib.request.Request(url, data=body, method=step["method"], headers=headers)
    timeout = (step.get("timeoutMs") or 5000) / 1000
    started = time.monotonic()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            status, ctype, raw = resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        status, ctype, raw = exc.code, exc.headers.get("Content-Type", ""), exc.read()
    return status, ctype, raw, time.monotonic() - started


def verify(step: dict, status: int, ctype: str, raw: bytes) -> tuple[list[str], object]:
    problems: list[str] = []
    exp = step.get("expected") or {}
    if status not in exp.get("statusCodes", []):
        problems.append(f"код {status}, ожидался один из {exp.get('statusCodes')}")
    want_type = exp.get("contentType")
    if want_type and not ctype.lower().startswith(want_type.lower()):
        problems.append(f"Content-Type «{ctype}», ожидался «{want_type}»")
    data = None
    if "json" in ctype.lower():
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            problems.append("тело не разбирается как JSON")
    for field in exp.get("requiredFields") or []:
        if data is None or not has_field(data, field):
            problems.append(f"нет обязательного поля «{field}»")
    schema = exp.get("bodySchema")
    if schema and data is not None and Draft202012Validator:
        for err in Draft202012Validator(schema).iter_errors(data):
            problems.append(f"bodySchema: {err.message}")
    return problems, data


def main() -> int:
    # Консоль Windows не в UTF-8: без этого «←» в сообщениях роняет вывод
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", default="DATA-API.yaml")
    ap.add_argument("--base-url", help="переопределить api.baseUrl (например, локальный стенд)")
    args = ap.parse_args()
    try:
        spec = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"Не удалось прочитать {args.file}: {exc}")
        return 2

    base = args.base_url or spec["api"]["baseUrl"]
    default_headers = spec["api"].get("defaultHeaders") or {}
    tokens = {k[len("DATA_API_TOKEN_"):].lower(): v for k, v in os.environ.items()
              if k.startswith("DATA_API_TOKEN_")}
    variables: dict = {}
    passed: set[str] = set()
    failed = 0

    print(f"DATA-API {spec.get('schemaVersion')} · {spec['solution']['name']} · {base}")
    if Draft202012Validator is None:
        print("  (bodySchema не проверяется: нет пакета jsonschema — pip install jsonschema)")
    print()
    for step in spec["checks"]:
        sid = step["id"]
        missing = [d for d in step.get("dependsOn") or [] if d not in passed]
        if missing:
            print(f"  [SKIP] {sid} — не прошли зависимости: {', '.join(missing)}")
            failed += 1
            continue
        try:
            status, ctype, raw, took = call(base, step, variables, default_headers, tokens)
            problems, data = verify(step, status, ctype, raw)
            for name, expr in (step.get("extract") or {}).items():
                try:
                    variables[name] = json_path(data, expr)
                except (KeyError, IndexError, TypeError, ValueError):
                    problems.append(f"extract {name} ← {expr}: значения нет")
        except Exception as exc:  # сеть, таймаут, нет токена
            problems, took = [f"{type(exc).__name__}: {exc}"], 0.0
        if problems:
            failed += 1
            print(f"  [FAIL] {sid} ({took:.1f} с)")
            for p in problems:
                print(f"         · {p}")
        else:
            passed.add(sid)
            print(f"  [ OK ] {sid} — {step['name']} ({took:.1f} с)")

    for step in spec.get("cleanup") or []:
        try:
            status, ctype, raw, _ = call(base, step, variables, default_headers, tokens)
            ok = status in (step.get("expected") or {}).get("statusCodes", [status])
            print(f"  [{'OK' if ok else '!!'}] cleanup {step['id']} → {status}")
        except Exception as exc:
            print(f"  [!!] cleanup {step['id']} → {type(exc).__name__}: {exc}")

    total = len(spec["checks"])
    print(f"\nИтог: {total - failed} из {total} проверок прошли")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
