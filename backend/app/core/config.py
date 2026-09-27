"""Конфигурация приложения. Всё берётся из переменных окружения / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> корень репозитория
REPO_ROOT = Path(__file__).resolve().parents[3]


# Тестовые аккаунты dev-входа. Настоящие id в MAX, которые встречались, —
# восьмизначные, шестизначный диапазон с ними не пересекается. Dev-вход пускает
# только сюда, уведомления сюда не уходят — таких аккаунтов в MAX нет.
# Границы продублированы во фронтенде (frontend/src/shared/max.ts), менять вместе.
TEST_USER_ID_MIN = 900_000
TEST_USER_ID_MAX = 999_999


def is_test_user_id(user_id: int) -> bool:
    return TEST_USER_ID_MIN <= user_id <= TEST_USER_ID_MAX


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Приложение ────────────────────────────────────────────────
    ENV: str = "development"
    LOG_LEVEL: str = "info"
    APP_NAME: str = "MAX Campus"

    # Публичный HTTPS-адрес мини-приложения. Используется в кнопке open_app и в диплинках.
    MINIAPP_PUBLIC_URL: str = "http://localhost:8000"

    # ── MAX ───────────────────────────────────────────────────────
    MAX_BOT_TOKEN: str = ""
    # Публичное имя бота (без @): поле web_app кнопки open_app и диплинки
    # max.ru/<имя>?startapp=…. Пусто — узнаётся один раз через GET /me.
    MAX_BOT_USERNAME: str = "t355_hakaton_max_bot"
    MAX_API_BASE: str = "https://platform-api2.max.ru"
    MAX_WEBHOOK_SECRET: str = "change-me"
    # Отклонять вебхук без заголовка X-Max-Bot-Api-Secret. Пока не подтверждено
    # по логам, что MAX присылает заголовок, выключено: иначе бот оглохнет.
    # Неверный секрет отклоняется всегда, независимо от флага.
    MAX_WEBHOOK_REQUIRE_SECRET: bool = False
    # Сторож вебхука: при старте и каждые 30 минут сверять подписку бота с
    # MINIAPP_PUBLIC_URL и снимать чужие. Включать только на основном сервере —
    # иначе локальный запуск уведёт бота с него.
    BOT_WEBHOOK_AUTOSUBSCRIBE: bool = False
    # Бандл корневых сертификатов Минцифры — без него TLS до platform-api2 не поднимается
    MAX_CA_BUNDLE: str = str(REPO_ROOT / "certs" / "russian_trusted_bundle.pem")
    # Лимит платформы — 30 rps. Держим запас.
    MAX_RATE_LIMIT_RPS: float = 20.0

    # Срок жизни подписи запуска. Bridge выдаёт её один раз при открытии
    # приложения, поэтому короче часа нельзя — сессия умирает посреди сценария.
    # Час рекомендует документация MAX Bridge.
    INIT_DATA_TTL_SECONDS: int = 3600
    # Режим разработки: пускать без валидации подписи (браузер вне MAX).
    # Только для тестовых id из TEST_USER_ID_MIN..TEST_USER_ID_MAX — выдать себя
    # за настоящего пользователя MAX так нельзя.
    ALLOW_DEV_AUTH: bool = True
    # Подписанная ссылка входа от бота (решение 057). Пока организаторы не
    # привязали мини-приложение к боту, кнопка в чате — обычная ссылка, и в
    # браузере нет подписи MAX: без токена человек вошёл бы тестовым
    # пользователем, и справка не пришла бы ему в чат. Бот кладёт в ссылку
    # ?lt=<id>.<срок>.<HMAC>. Пустой секрет выводится из MAX_BOT_TOKEN —
    # отдельный ручной секрет не нужен; смена секрета гасит все выданные ссылки.
    LINK_SECRET: str = ""
    LINK_TTL_SECONDS: int = 86400

    # ── Демо для экспертов ────────────────────────────────────────
    # Кнопка «Попробовать как студент (демо)»: каждому аккаунту — своя копия
    # демо-студента (зачётка DEMO-<id>) и роль деканата в один тап. Коды привязки
    # одноразовые и кончаются на втором эксперте, копии — нет. Решение 055.
    DEMO_MODE: bool = True
    # Предохранитель на весь сервер: сколько копий можно создать за час.
    # Скрипт с тестовыми id иначе набил бы базу тысячами копий.
    DEMO_COPIES_PER_HOUR: int = 60

    # ── База данных ───────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://campus:campus@localhost:5432/campus"

    # ── Файлы ─────────────────────────────────────────────────────
    DATA_DIR: str = str(REPO_ROOT / "data")

    # ── LLM ───────────────────────────────────────────────────────
    LLM_PROVIDER: str = "yandex"
    YC_API_KEY: str = ""
    YC_FOLDER_ID: str = ""
    YC_OPENAI_BASE: str = "https://ai.api.cloud.yandex.net/v1"
    LLM_MODEL_MAIN: str = "yandexgpt/latest"
    LLM_MODEL_CHEAP: str = "yandexgpt-lite/latest"

    EMBEDDING_URL: str = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"
    EMBEDDING_MODEL_DOC: str = "text-search-doc/latest"
    EMBEDDING_MODEL_QUERY: str = "text-search-query/latest"
    EMBEDDING_DIM: int = 256

    # Максимум итераций цикла вызова инструментов (решение 020)
    ASSISTANT_MAX_TOOL_ITERATIONS: int = 4
    # Сколько фрагментов базы знаний подмешивать (решение 019 — RAG принудительный)
    RAG_TOP_K: int = 5

    @property
    def model_uri_main(self) -> str:
        return f"gpt://{self.YC_FOLDER_ID}/{self.LLM_MODEL_MAIN}"

    @property
    def model_uri_cheap(self) -> str:
        return f"gpt://{self.YC_FOLDER_ID}/{self.LLM_MODEL_CHEAP}"

    @property
    def documents_dir(self) -> Path:
        p = Path(self.DATA_DIR) / "documents"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def uploads_dir(self) -> Path:
        p = Path(self.DATA_DIR) / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def llm_enabled(self) -> bool:
        return bool(self.YC_API_KEY and self.YC_FOLDER_ID)

    @property
    def bot_enabled(self) -> bool:
        return bool(self.MAX_BOT_TOKEN)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
