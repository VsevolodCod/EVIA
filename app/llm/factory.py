from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.mock import MockLLMProvider
from app.llm.ollama_provider import OllamaProvider, OllamaModel
from app.llm.openai_provider import OpenAIProvider, OpenAIModel


def create_llm_provider(settings: Settings) -> LLMProvider:
    """
    Возвращает сконструированный объект одного из подклассов ``LLMProvider``

    :param settings: Объект настроек, состоящих из данных из ``.env``
    :return:
    """

    if settings.llm_provider == "mock":
        return MockLLMProvider()

    if settings.llm_provider == "openai":
        model = OpenAIModel(settings)
        return OpenAIProvider(
            model=model,
            model_name=settings.llm_model
        )

    if settings.llm_provider == "ollama":
        model = OllamaModel(settings)
        return OllamaProvider(
            model=model
        )

    raise ValueError(
        f"Unsupported LLM_PROVIDER: {settings.llm_provider}"
    )
