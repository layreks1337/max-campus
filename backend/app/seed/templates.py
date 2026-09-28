"""Шаблоны заявок.

Это ДАННЫЕ, а не код. Новый тип справки добавляется словарём в список ниже —
ни одна строчка Python при этом не меняется. В этом весь смысл движка.

`auto_issue: True` — типовой документ выдаётся сразу при подаче, по данным
контингента, без очереди сотрудника. Поле с `manual_review: True`, если его
заполнили, делает заявку нетиповой: она идёт в очередь деканата как обычно.
"""

from __future__ import annotations

TEMPLATES: list[dict] = [
    {
        "key": "study_certificate",
        "title": "Справка об обучении",
        "short_title": "Справка об обучении",
        "description": "Подтверждает факт обучения. Нужна для соцзащиты, банка, работодателя.",
        "icon": "📄",
        "category": "Справки",
        "sla_hours": 72,
        "doc_template": "study_certificate",
        "produces_document": True,
        "auto_issue": True,
        "sort_order": 10,
        "schema_json": {
            "fields": [
                {
                    "name": "purpose",
                    "type": "select",
                    "label": "Куда нужна справка",
                    "options": [
                        "По месту требования",
                        "В органы соцзащиты",
                        "В банк",
                        "Работодателю",
                        "В пенсионный фонд",
                    ],
                    "required": True,
                },
                {
                    "name": "copies",
                    "type": "number",
                    "label": "Количество экземпляров",
                    "min": 1,
                    "max": 5,
                    "default": 1,
                },
                {
                    "name": "need_original",
                    "type": "bool",
                    "label": "Нужен оригинал с печатью",
                    "hint": "Электронную копию PDF выдадим в любом случае",
                    "default": False,
                    # бумагу с печатью готовит человек — автоматом не выдать
                    "manual_review": True,
                },
                {
                    "name": "comment",
                    "type": "textarea",
                    "label": "Комментарий",
                    "placeholder": "Если есть особые требования к формулировке",
                    "maxLength": 500,
                    # особая формулировка — нетиповая справка
                    "manual_review": True,
                },
            ]
        },
        "route_json": [
            {"status": "IN_REVIEW", "actor_role": "STAFF_CLERK"},
            {"status": "SIGNING", "actor_role": "STAFF_HEAD"},
            {"status": "READY"},
        ],
    },
    {
        "key": "military_certificate",
        "title": "Справка в военный комиссариат",
        "short_title": "Справка в военкомат",
        "description": "Форма для предоставления отсрочки. Срок — 3 рабочих дня.",
        "icon": "🎖",
        "category": "Справки",
        "sla_hours": 72,
        "doc_template": "military_certificate",
        "produces_document": True,
        "sort_order": 20,
        "schema_json": {
            "fields": [
                {
                    "name": "commissariat",
                    "type": "text",
                    "label": "Военкомат",
                    "placeholder": "Например: Октябрьского района г. Иркутска",
                    "required": True,
                    "maxLength": 200,
                },
                {
                    "name": "need_original",
                    "type": "bool",
                    "label": "Нужен оригинал с печатью",
                    "default": True,
                },
            ]
        },
        "route_json": [
            {"status": "IN_REVIEW", "actor_role": "STAFF_CLERK"},
            {"status": "SIGNING", "actor_role": "STAFF_HEAD"},
            {"status": "READY"},
        ],
    },
    {
        "key": "income_certificate",
        "title": "Справка о размере стипендии",
        "short_title": "Справка о стипендии",
        "description": "Сведения о начисленной стипендии за выбранный период.",
        "icon": "💰",
        "category": "Справки",
        "sla_hours": 96,
        "doc_template": "income_certificate",
        "produces_document": True,
        "sort_order": 30,
        "schema_json": {
            "fields": [
                {
                    "name": "period",
                    "type": "select",
                    "label": "Период",
                    "options": [
                        "Последние 3 месяца",
                        "Последние 6 месяцев",
                        "Текущий учебный год",
                        "Предыдущий учебный год",
                    ],
                    "required": True,
                },
                {
                    "name": "purpose",
                    "type": "select",
                    "label": "Куда предоставляется",
                    "options": ["В органы соцзащиты", "В банк", "По месту требования"],
                    "required": True,
                },
            ]
        },
        "route_json": [
            {"status": "IN_REVIEW", "actor_role": "STAFF_CLERK"},
            {"status": "SIGNING", "actor_role": "STAFF_HEAD"},
            {"status": "READY"},
        ],
    },
    {
        "key": "social_scholarship",
        "title": "Заявление на государственную социальную стипендию",
        "short_title": "Социальная стипендия",
        "description": "Для льготных категорий. Нужен документ-основание из соцзащиты.",
        "icon": "🤝",
        "category": "Стипендии",
        "sla_hours": 120,
        "doc_template": "decision",
        "produces_document": True,
        "sort_order": 40,
        "schema_json": {
            "fields": [
                {
                    "name": "category",
                    "type": "select",
                    "label": "Основание",
                    "options": [
                        "Малоимущая семья",
                        "Инвалидность I или II группы",
                        "Потеря кормильца",
                        "Сирота или без попечения родителей",
                        "Ветеран боевых действий",
                    ],
                    "required": True,
                },
                {
                    "name": "doc_scan",
                    "type": "file",
                    "label": "Подтверждающий документ",
                    "hint": "Справка из органов соцзащиты, фото или PDF",
                    "accept": ["image/*", "application/pdf"],
                    "maxSizeMb": 10,
                    "required": True,
                },
                {
                    "name": "period",
                    "type": "select",
                    "label": "Семестр",
                    "options": ["Осенний семестр", "Весенний семестр"],
                    "required": True,
                },
                {
                    "name": "comment",
                    "type": "textarea",
                    "label": "Комментарий",
                    "maxLength": 500,
                },
            ]
        },
        "route_json": [
            {"status": "IN_REVIEW", "actor_role": "STAFF_CLERK"},
            {"status": "SIGNING", "actor_role": "STAFF_HEAD"},
            {"status": "READY"},
        ],
    },
    {
        "key": "financial_aid",
        "title": "Заявление на материальную помощь",
        "short_title": "Материальная помощь",
        "description": "Единовременная выплата при трудной жизненной ситуации.",
        "icon": "🆘",
        "category": "Стипендии",
        "sla_hours": 168,
        "doc_template": "decision",
        "produces_document": True,
        "sort_order": 50,
        "schema_json": {
            "fields": [
                {
                    "name": "reason",
                    "type": "select",
                    "label": "Причина обращения",
                    "options": [
                        "Тяжёлое материальное положение",
                        "Лечение и медицинские расходы",
                        "Рождение ребёнка",
                        "Смерть близкого родственника",
                        "Утрата имущества",
                        "Иное",
                    ],
                    "required": True,
                },
                {
                    "name": "details",
                    "type": "textarea",
                    "label": "Опишите ситуацию",
                    "placeholder": "Кратко, что произошло",
                    "required": True,
                    "minLength": 20,
                    "maxLength": 1000,
                },
                {
                    "name": "doc_scan",
                    "type": "file",
                    "label": "Подтверждающие документы",
                    "accept": ["image/*", "application/pdf"],
                    "maxSizeMb": 10,
                },
            ]
        },
        "route_json": [
            {"status": "IN_REVIEW", "actor_role": "STAFF_CLERK"},
            {"status": "SIGNING", "actor_role": "STAFF_HEAD"},
            {"status": "READY"},
        ],
    },
    {
        "key": "dormitory",
        "title": "Заявление на место в общежитии",
        "short_title": "Общежитие",
        "description": "Заселение или продление. Рассматривается жилищной комиссией.",
        "icon": "🏠",
        "category": "Быт",
        "sla_hours": 168,
        "doc_template": "decision",
        "produces_document": True,
        "sort_order": 60,
        "schema_json": {
            "fields": [
                {
                    "name": "action",
                    "type": "select",
                    "label": "Что нужно",
                    "options": ["Заселение", "Продление проживания", "Смена комнаты"],
                    "required": True,
                },
                {
                    "name": "priority_ground",
                    "type": "select",
                    "label": "Льготное основание",
                    "options": [
                        "Нет",
                        "Сирота или без попечения родителей",
                        "Инвалидность",
                        "Малоимущая семья",
                        "Иногородний",
                    ],
                    "default": "Нет",
                },
                {
                    "name": "comment",
                    "type": "textarea",
                    "label": "Комментарий",
                    "maxLength": 500,
                },
            ]
        },
        "route_json": [
            {"status": "IN_REVIEW", "actor_role": "STAFF_CLERK"},
            {"status": "SIGNING", "actor_role": "STAFF_HEAD"},
            {"status": "READY"},
        ],
    },
    {
        "key": "academic_leave",
        "title": "Заявление на академический отпуск",
        "short_title": "Академический отпуск",
        "description": "По медицинским, семейным или иным обстоятельствам.",
        "icon": "⏸",
        "category": "Обучение",
        "sla_hours": 168,
        "doc_template": "decision",
        "produces_document": True,
        "sort_order": 70,
        "schema_json": {
            "fields": [
                {
                    "name": "reason",
                    "type": "select",
                    "label": "Основание",
                    "options": [
                        "Медицинские показания",
                        "Семейные обстоятельства",
                        "Призыв на военную службу",
                        "Уход за ребёнком",
                        "Иные исключительные случаи",
                    ],
                    "required": True,
                },
                {
                    "name": "start_date",
                    "type": "date",
                    "label": "Предполагаемая дата начала",
                    "required": True,
                },
                {
                    "name": "doc_scan",
                    "type": "file",
                    "label": "Подтверждающий документ",
                    "hint": "Заключение врачебной комиссии, повестка и т.п.",
                    "accept": ["image/*", "application/pdf"],
                    "maxSizeMb": 10,
                    "required": True,
                },
            ]
        },
        "route_json": [
            {"status": "IN_REVIEW", "actor_role": "STAFF_CLERK"},
            {"status": "SIGNING", "actor_role": "STAFF_HEAD"},
            {"status": "READY"},
        ],
    },
    {
        "key": "session_summons",
        "title": "Справка-вызов на сессию",
        "short_title": "Справка-вызов",
        "description": "Для заочной формы — основание для учебного отпуска у работодателя.",
        "icon": "📆",
        "category": "Справки",
        "sla_hours": 96,
        "doc_template": "decision",
        "produces_document": True,
        "sort_order": 80,
        "schema_json": {
            "fields": [
                {
                    "name": "employer",
                    "type": "text",
                    "label": "Название организации-работодателя",
                    "required": True,
                    "maxLength": 200,
                },
                {
                    "name": "session",
                    "type": "select",
                    "label": "Сессия",
                    "options": ["Зимняя", "Летняя"],
                    "required": True,
                },
            ]
        },
        "route_json": [
            {"status": "IN_REVIEW", "actor_role": "STAFF_CLERK"},
            {"status": "SIGNING", "actor_role": "STAFF_HEAD"},
            {"status": "READY"},
        ],
    },
    {
        "key": "support_question",
        "title": "Обращение в деканат",
        "short_title": "Обращение",
        "description": "Вопрос сотруднику, если ассистент не смог помочь.",
        "icon": "💬",
        "category": "Обращения",
        "sla_hours": 48,
        "doc_template": "none",
        "produces_document": False,
        "sort_order": 999,
        "schema_json": {
            "fields": [
                {
                    "name": "question",
                    "type": "textarea",
                    "label": "Вопрос",
                    "required": True,
                    "minLength": 5,
                    "maxLength": 1000,
                },
                {"name": "source", "type": "text", "label": "Источник", "maxLength": 40},
            ]
        },
        "route_json": [
            {"status": "IN_REVIEW", "actor_role": "STAFF_CLERK"},
            {"status": "READY"},
        ],
    },
]
