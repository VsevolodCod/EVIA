import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class PostgresSettings:
    """Optional deployment-only configuration for one PostgreSQL source."""

    dsn: str
    allowed_tables: frozenset[tuple[str, str]]
    connect_timeout_seconds: int
    statement_timeout_ms: int

    @property
    def enabled(self) -> bool:
        return bool(self.dsn and self.allowed_tables)


def _parse_allowed_tables(value: str) -> frozenset[tuple[str, str]]:
    if not value.strip():
        return frozenset()
    tables: set[tuple[str, str]] = set()
    for item in value.split(","):
        schema_name, separator, table_name = item.strip().partition(".")
        if not separator or not schema_name or not table_name or "." in table_name:
            raise ValueError("POSTGRES_ALLOWED_TABLES entries must use schema.table")
        tables.add((schema_name, table_name))
    return frozenset(tables)


class Settings:
    def __init__(self) -> None:
        self.llm_provider = os.getenv("LLM_PROVIDER", "mock").lower()
        self.llm_model = os.getenv("LLM_MODEL", "")
        self.thinking = bool(int(os.getenv("THINKING", "0")))
        self.timeout = float(os.getenv("TIMEOUT", "120"))
        self.max_tokens_generate = int(os.getenv("MAX_TOKENS_G", "256"))

        self.openai_base_url = os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        ).rstrip("/")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")

        self.ollama_base_url = os.getenv(
            "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
        ).rstrip("/")
        self.ollama_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "10m")

        self.data_dir = Path(os.getenv("BI_DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
        self.chat_db_path = Path(
            os.getenv("CHAT_DB_PATH", str(self.data_dir / "chats.db"))
        ).resolve()
        self.catalog_db_path = Path(
            os.getenv("CATALOG_DB_PATH")
            or os.getenv("BI_CATALOG_DB")
            or str(self.data_dir / "catalog.db")
        ).resolve()

        self.postgres = PostgresSettings(
            dsn=os.getenv("POSTGRES_DSN", ""),
            allowed_tables=_parse_allowed_tables(os.getenv("POSTGRES_ALLOWED_TABLES", "")),
            connect_timeout_seconds=max(1, int(os.getenv("POSTGRES_CONNECT_TIMEOUT_SECONDS", "5"))),
            statement_timeout_ms=max(1, int(os.getenv("POSTGRES_STATEMENT_TIMEOUT_MS", "10000"))),
        )

        # A missing/mistyped flag on Railway must never expose owned records.
        self.auth_enabled = bool(os.getenv("RAILWAY_ENVIRONMENT")) or os.getenv("AUTH_ENABLED", "0") == "1"
        self.auth_database_url = os.getenv("AUTH_DATABASE_URL", "")
        self.auth_secret = os.getenv("AUTH_SECRET", "")
        self.auth_bootstrap_email = os.getenv("AUTH_BOOTSTRAP_EMAIL", "")
        self.auth_bootstrap_password = os.getenv("AUTH_BOOTSTRAP_PASSWORD", "")

        self.agent_max_steps = max(
            1, int(os.getenv("AGENT_MAX_STEPS", "5"))
        )

        self.agent_max_steps = max(
            1, int(os.getenv("AGENT_MAX_STEPS", "5"))
        )

        self.agent_llm_retry_max_attempts = max(
            1, int(os.getenv("AGENT_LLM_RETRY_MAX_ATTEMPTS", "5"))
        )
        self.agent_llm_retry_base_delay_seconds = max(
            0.0, float(os.getenv("AGENT_LLM_RETRY_BASE_DELAY_SECONDS", "0.3"))
        )
        self.agent_llm_retry_backoff_multiplier = max(
            1.0, float(os.getenv("AGENT_LLM_RETRY_BACKOFF_MULTIPLIER", "2.0"))
        )
        self.agent_llm_retry_max_delay_seconds = max(
            0.0, float(os.getenv("AGENT_LLM_RETRY_MAX_DELAY_SECONDS", "5.0"))
        )

    def prepare_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.chat_db_path.parent.mkdir(parents=True, exist_ok=True)

    def public_settings(self) -> dict[str, object]:
        """Expose only settings that are safe to return in diagnostics."""
        return {
            "postgres_configured": self.postgres.enabled,
            "postgres_table_count": len(self.postgres.allowed_tables),
        }


# @lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_directories()
    return settings


if __name__ == "__main__":
    print(PROJECT_ROOT / ".env")
    print(os.getenv("LLM_PROVIDER", "mock").lower())
