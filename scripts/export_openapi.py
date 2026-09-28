#!/usr/bin/env python
"""Выгрузка схемы OpenAPI в openapi.json в корне репозитория.

Кейс (с. 10) требует файл openapi.yaml или openapi.json, а DATA-API.yaml ссылается
на него (`api.openapi: ./openapi.json`): валидатор организаторов сверяет с ним пути
и методы обязательных проверок. Файл — ровно то, что сервер отдаёт на
/api/openapi.json, без правок руками; после изменения роутов его перегенерируют.

Использование:
    python scripts/export_openapi.py                         из кода приложения
    python scripts/export_openapi.py --url http://127.0.0.1:8000   с работающего сервера
    python scripts/export_openapi.py --check                 файл совпадает с кодом?

Из кода нужны зависимости бэкенда (backend/.venv). Если их нет, схема берётся
из контейнера campus-app — из собранного образа, то есть из кода последней
сборки. Режим --url обходится стандартной библиотекой. Код выхода: 0 — готово
(или файл актуален), 1 — схема не получена (или файл устарел).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "campus-app"
DUMP = "import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False))"


def from_code() -> tuple[dict, str]:
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from app.main import app
    except ImportError as exc:
        print(f"Зависимостей бэкенда нет ({exc.name}) — беру схему из контейнера {CONTAINER}",
              file=sys.stderr)
        proc = subprocess.run(
            ["docker", "exec", CONTAINER, "python", "-c", DUMP],
            capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip()[-600:] or "docker exec завершился с ошибкой") from None
        return json.loads(proc.stdout), f"контейнер {CONTAINER}"
    return app.openapi(), "код приложения"


def from_url(url: str) -> tuple[dict, str]:
    url = url.rstrip("/")
    if not url.endswith(".json"):
        url += "/api/openapi.json"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8")), url


def render(spec: dict) -> str:
    # Отступ и кириллица как есть — файл читают люди и диффы в git
    return json.dumps(spec, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Выгрузка openapi.json")
    ap.add_argument("--url", help="взять схему с работающего сервера, например http://127.0.0.1:8000")
    ap.add_argument("-o", "--output", default=str(ROOT / "openapi.json"),
                    help="куда записать (по умолчанию openapi.json в корне репозитория)")
    ap.add_argument("--check", action="store_true",
                    help="не записывать, а сверить с файлом: код выхода 1, если он устарел")
    args = ap.parse_args()

    try:
        spec, source = from_url(args.url) if args.url else from_code()
    except Exception as exc:  # сеть, docker, импорт приложения
        print(f"Схема не получена: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    text = render(spec)
    out = Path(args.output)
    operations = sum(
        1 for item in spec.get("paths", {}).values()
        for method in item if method in {"get", "post", "put", "patch", "delete"}
    )
    summary = f"OpenAPI {spec.get('openapi')}: {len(spec.get('paths', {}))} путей, {operations} операций"

    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current == text:
            print(f"{out.name} актуален — {summary} ({source})")
            return 0
        print(f"{out.name} расходится со схемой ({source}): перегенерируйте без --check")
        return 1

    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"{out} ← {source} · {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
