import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


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

        self.data_dir = Path(os.getenv("BI_DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
        self.chat_db_path = Path(
            os.getenv("CHAT_DB_PATH", "data/chats.db")
        ).resolve()
        self.catalog_db_path = Path(
            os.getenv("CATALOG_DB_PATH", "data/catalog.db")
        ).resolve()

        self.agent_max_steps = max(
            1, int(os.getenv("AGENT_MAX_STEPS", "5"))
        )

    def prepare_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.chat_db_path.parent.mkdir(parents=True, exist_ok=True)


# @lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_directories()
    return settings


if __name__ == "__main__":
    print(PROJECT_ROOT / ".env")
    print(os.getenv("LLM_PROVIDER", "mock").lower())