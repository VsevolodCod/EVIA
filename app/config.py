import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.llm_provider = os.getenv("LLM_PROVIDER", "mock").lower()
        self.llm_model = os.getenv("LLM_MODEL", "")

        self.openai_base_url = os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        ).rstrip("/")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")

        self.ollama_base_url = os.getenv(
            "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
        ).rstrip("/")

        self.data_dir = Path(os.getenv("BI_DATA_DIR", "./data")).resolve()
        self.catalog_db = Path(
            os.getenv("BI_CATALOG_DB", "./data/catalog.sqlite3")
        ).resolve()

        self.agent_max_steps = max(
            1, int(os.getenv("AGENT_MAX_STEPS", "5"))
        )

    def prepare_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_db.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_directories()
    return settings
