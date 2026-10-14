from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DataSource(BaseModel):
    source_id: str
    name: str
    source_type: str
    status: str = "registered"
    created_at: datetime = Field(default_factory=utc_now)
    schema_version: int = 1


class SchemaField(BaseModel):
    name: str
    inferred_type: str = "unknown"
    nullable: bool | None = None
    is_identifier_candidate: bool = False
    description: str | None = None


class SchemaObject(BaseModel):
    object_id: str
    name: str
    object_type: str = "unknown"
    fields: list[SchemaField] = Field(default_factory=list)
    row_count: int | None = None


class SchemaRelation(BaseModel):
    left_object_id: str
    left_field: str
    right_object_id: str
    right_field: str
    discovery_method: str = "unknown"
    confidence: float | None = None


class SourceSchema(BaseModel):
    source_id: str
    version: int = 1
    discovered_at: datetime = Field(default_factory=utc_now)
    objects: list[SchemaObject] = Field(default_factory=list)
    relations: list[SchemaRelation] = Field(default_factory=list)


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None

    # Нужны для корректного продолжения диалога
    # после вызова инструментов в API провайдера.
    tool_calls: list[dict[str, Any]] | None = None


class LLMResponse(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    raw_tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class ToolResult(BaseModel):
    tool_name: str
    ok: bool
    data: Any = None
    error: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    source_ids: list[str] = Field(default_factory=list)


class AskResponse(BaseModel):
    answer: str
    steps: int
    tool_results: list[ToolResult] = Field(default_factory=list)
