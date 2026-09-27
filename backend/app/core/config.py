"""Конфигурация приложения. Всё берётся из переменных окружения / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> корень репозитория
REPO_ROOT = Path(__file__).resolve().parents[3]


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
    MAX_API_BASE: str = "https://platform-api2.max.ru"
    MAX_WEBHOOK_SECRET: str = "change-me"
    # Сторож вебхука: при старте и каждые 30 минут сверять подписку бота с
    # MINIAPP_PUBLIC_URL и снимать чужие. Включать только на основном сервере —
    # иначе локальный запуск уведёт бота с него.
    BOT_WEBHOOK_AUTOSUBSCRIBE: bool = False
    # Бандл корневых сертификатов Минцифры — без него TLS до platform-api2 не поднимается
    MAX_CA_BUNDLE: str = str(REPO_ROOT / "certs" / "russian_trusted_bundle.pem")
    # Лимит платформы — 30 rps. Держим запас.
    MAX_RATE_LIMIT_RPS: float = 20.0

    INIT_DATA_TTL_SECONDS: int = 900
    # Режим разработки: пускать без валидации подписи (браузер вне MAX).
    # В production ОБЯЗАТЕЛЬНО False.
    ALLOW_DEV_AUTH: bool = True

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
