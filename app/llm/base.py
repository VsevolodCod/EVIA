from abc import ABC, abstractmethod

from app.models import LLMMessage, LLMResponse
from typing import List, Any
import asyncio


__all__ = ["Model", "AsyncModel", "LLMProvider"]

# Тут только необходимые


class StreamEncoder:

    """
    Класс итерации по полученным токенам при потоковом выходе синхронной модели.
    Используется в связке с ``StreamModel``
    """

    full_text: str
    done: bool

    def __iter__(self):
        ...


class AsyncStreamEncoder:

    """
    Класс итерации по полученным токенам при потоковом выходе синхронной модели.
    Используется в связке с ``AsyncStreamModel``
    """

    full_text: str
    done: bool

    async def __aiter__(self):
        ...


"""
    Все объекты моделей генерируют некоторые выходные по ``payload``.
    Объект провайдера использует модели, разбирая входящие данные в виде ``LLMMessage`` и набор инструментов на 
    нужный ``payload``
"""


class Model(ABC):
    """Базовый интерфейс синхронной модели."""

    @abstractmethod
    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Выполнить запрос и вернуть ответ API."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


class AsyncModel(ABC):
    """Базовый интерфейс асинхронной модели."""

    @abstractmethod
    async def generate(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Выполнить запрос и вернуть ответ API."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


class StreamModel(Model):
    """
    Его подклассы по сути являются переходниками между импортируемыми классами моделей.
    Работает синхронно, но отдает токены по мере их получения.

    Пока не используется
    """

    @abstractmethod
    def generate(self, payload: dict[str, Any]) -> StreamEncoder:
        raise NotImplementedError


class AsyncStreamModel(Model):
    """
    Его подклассы по сути являются переходниками между импортируемыми классами моделей.
    Работает асинхронно, отдает токены по мере их получения.

    Пока не используется
    """

    @abstractmethod
    async def generate(self, payload: dict[str, Any]) -> AsyncStreamEncoder:
        raise NotImplementedError


class LLMProvider(ABC):

    """
    Переходник между классами моделей и внешним взаимодействием.
    Сериализует объекты сообщений в строки. Обрабатывает вызов инструментов (но сам их не вызывает)
    """

    @abstractmethod
    async def chat(
        self,
        messages: List[LLMMessage],
        tools: List[dict] | None = None,
    ) -> LLMResponse:
        """Send conversation history and return text or tool calls."""
        raise NotImplementedError

