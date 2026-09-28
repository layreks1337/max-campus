"""Схема OpenAPI, которая совпадает с настоящими ответами сервера.

FastAPI сам описывает только успешный ответ и 422 в своём формате `{detail: […]}`,
а сервер отказывает единым конвертом `{error: {code, message, details}}` (main.py).
Здесь схема дописывается по коду, а не руками (решение 080):
  • 422 — конверт ErrorResponse вместо формата FastAPI HTTPValidationError;
  • 401 — у каждого метода с входом (зависимость get_init_data), 403 — у методов
    сотрудника (require_staff), 409 BINDING_REQUIRED — где нужен привязанный студент;
  • 413 — у методов с телом запроса: лимит размера для всех (core/limits.py).
Остальные отказы роут объявляет сам: `responses=errors(404, 409)` (api/schemas.py).
Вход описан схемами безопасности MaxAuth и MaxInitDataHeader (core/deps.py).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute, iter_route_contexts

from app.api.schemas import ERROR_DESCRIPTIONS, ErrorResponse
from app.core.deps import get_init_data, require_binding, require_staff

_REF = "#/components/schemas/ErrorResponse"

# Зависимость → какой отказ она даёт любому методу, в который входит
_BY_DEPENDENCY: tuple[tuple[Callable, int, str], ...] = (
    (get_init_data, 401, ERROR_DESCRIPTIONS[401]),
    (require_staff, 403, "Нужны права сотрудника (FORBIDDEN)"),
    (require_binding, 409, "Студенческий не привязан — нужен вход (BINDING_REQUIRED)"),
)


def _calls(dependant: Dependant) -> set[Callable]:
    found: set[Callable] = set()
    for dep in dependant.dependencies:
        if dep.call is not None:
            found.add(dep.call)
        found |= _calls(dep)
    return found


def _error(description: str) -> dict[str, Any]:
    return {"description": description, "content": {"application/json": {"schema": {"$ref": _REF}}}}


def _document_errors(app: FastAPI, schema: dict[str, Any]) -> None:
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    if "ErrorResponse" not in components:
        model = ErrorResponse.model_json_schema(ref_template="#/components/schemas/{model}")
        components.update(model.pop("$defs", {}))
        components["ErrorResponse"] = model

    # Роутеры с префиксом FastAPI 0.141 хранит не плоским списком — обходим так же,
    # как get_openapi: путь с префиксом берётся из контекста, зависимости — у роута
    for route in iter_route_contexts(app.routes):
        original = route.original_route
        if not isinstance(original, APIRoute) or not original.include_in_schema:
            continue
        calls = _calls(original.dependant)
        for method in route.methods or ():
            operation = schema["paths"].get(route.path_format, {}).get(method.lower())
            if operation is None:
                continue
            responses = operation.setdefault("responses", {})
            for call, code, description in _BY_DEPENDENCY:
                if call in calls:
                    responses.setdefault(str(code), _error(description))
            if "requestBody" in operation:
                responses.setdefault("413", _error(ERROR_DESCRIPTIONS[413]))
            if "HTTPValidationError" in str(responses.get("422", "")):
                responses["422"] = _error(ERROR_DESCRIPTIONS[422])
            # По порядку кодов: 200, 201, 401, 403…
            operation["responses"] = dict(sorted(responses.items(), key=lambda kv: kv[0]))

    # Формат FastAPI для 422 больше нигде не упоминается
    if "HTTPValidationError" not in str(schema["paths"]):
        components.pop("HTTPValidationError", None)
        components.pop("ValidationError", None)


def install_openapi(app: FastAPI) -> None:
    def build() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title,
                version=app.version,
                openapi_version=app.openapi_version,
                description=app.description,
                routes=app.routes,
            )
            _document_errors(app, schema)
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = build  # type: ignore[method-assign]
