from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DataSource(BaseModel):
    source_id: str
    # A source can later receive a new immutable snapshot without changing the
    # public source identifier.  CSV imports create their first snapshot at
    # registration time.
    snapshot_id: str | None = None
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
    parser_version: int = 1
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


class ModelTiming(BaseModel):
    elapsed_ms: float = Field(default=0, ge=0)
    model: str | None = None
    load_ms: float | None = Field(default=None, ge=0)
    prompt_ms: float | None = Field(default=None, ge=0)
    generation_ms: float | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    generated_tokens: int | None = Field(default=None, ge=0)


class AgentTiming(BaseModel):
    elapsed_ms: float = Field(default=0, ge=0)
    llm_ms: float = Field(default=0, ge=0)
    tools_ms: float = Field(default=0, ge=0)
    calls: list[ModelTiming] = Field(default_factory=list)


class LLMResponse(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    raw_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    timing: ModelTiming | None = None


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
    chat_id: str | None = None
    timing: AgentTiming | None = None


class ChatMessage(LLMMessage):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)


class Chat(BaseModel):
    chat_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = "Новый чат"
    temporary: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatCreateRequest(BaseModel):
    title: str = Field(
        default="Новый чат",
        min_length=1,
        max_length=200,
    )


class ChatSummary(BaseModel):
    chat_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatHistoryResponse(BaseModel):
    chat_id: str
    title: str
    messages: list[ChatMessage]
    total_messages: int
    next_offset: int | None
    next_before: int | None = None
    has_more: bool
