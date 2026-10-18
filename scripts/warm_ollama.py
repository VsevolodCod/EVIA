"""Explicit preload of the configured Ollama model, without sending source data."""
import asyncio
from time import perf_counter

from app.config import Settings
from app.llm.ollama_provider import OllamaModel


async def main():
    settings = Settings()
    if settings.llm_provider != 'ollama':
        raise SystemExit('Set LLM_PROVIDER=ollama first')
    started = perf_counter()
    data = await OllamaModel(settings).generate({'messages': []})
    print(f'Model: {settings.llm_model}; preload: {perf_counter() - started:.1f}s; done={data.get("done")}')


if __name__ == '__main__':
    asyncio.run(main())
