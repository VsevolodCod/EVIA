from abc import ABC, abstractmethod
from typing import Any

from app.models import DataSource, SourceSchema


class DataSourceAdapter(ABC):
    """
    Общий контракт для CSV, PostgreSQL, ClickHouse и других источников.
    """

    @abstractmethod
    def test_connection(self, source: DataSource) -> tuple[bool, str]:
        pass

    @abstractmethod
    def introspect_schema(self, source: DataSource) -> SourceSchema:
        pass

    @abstractmethod
    def preview(
        self,
        source: DataSource,
        object_name: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def profile(
        self,
        source: DataSource,
        object_name: str,
    ) -> dict[str, Any]:
        pass
