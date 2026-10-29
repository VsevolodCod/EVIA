from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, JsonValue


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ImportReport(BaseModel):
    sha256: str = ""
    size_bytes: int = 0
    encoding: str = ""
    delimiter: str = ""
    rows_read: int = 0
    accepted_rows: int = 0
    rejected_rows: int = 0
    blank_lines: int = 0
    column_types: dict[str, str] = Field(default_factory=dict)
    column_nullable: dict[str, bool] = Field(default_factory=dict)
    typed_sql_types: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class CSVVersion(BaseModel):
    snapshot_id: str
    raw_filename: str
    normalized_filename: str
    report: ImportReport


class DataSource(BaseModel):
    source_id: str
    # A source can later receive a new immutable snapshot without changing the
    # public source identifier.  CSV imports create their first snapshot at
    # registration time.
    snapshot_id: str | None = None
    name: str
    source_type: str
    # Remote source metadata is safe to persist. Connection credentials remain
    # process configuration and never belong in this model or catalog payload.
    schema_name: str | None = None
    table_name: str | None = None
    status: str = "registered"
    created_at: datetime = Field(default_factory=utc_now)
    schema_version: int = 1
    import_report: ImportReport | None = None
    csv_versions: list[CSVVersion] = Field(default_factory=list)


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
    provider_total_ms: float | None = Field(default=None, ge=0)
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
    finish_reason: str | None = None


class ToolResult(BaseModel):
    tool_name: str
    ok: bool
    data: Any = None
    error: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    source_ids: list[str] = Field(default_factory=list)
    dashboard_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    steps: int
    tool_results: list[ToolResult] = Field(default_factory=list)
    chat_id: str | None = None
    timing: AgentTiming | None = None

    # Внутренняя история вызовов инструментов для сохранения в чате.
    conversation_trace: list[LLMMessage] | None = Field(
        default_factory=list,
        exclude=True,
    )


class AnalysisPayload(BaseModel):
    """Versioned JSON snapshot; AgentResponse is validated at the route boundary."""

    # Readers keep future envelopes opaque so archived text stays accessible.
    version: int = Field(default=1, ge=1)
    response: dict[str, JsonValue]


class ChatMessage(LLMMessage):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    analysis_payload: AnalysisPayload | None = None
    response: dict[str, Any] | None = None  # Legacy dashboard snapshots.


class Chat(BaseModel):
    chat_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = "Новый чат"
    temporary: bool = True
    source_id: str | None = None
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
    source_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatHistoryResponse(BaseModel):
    chat_id: str
    title: str
    source_id: str | None = None
    messages: list[ChatMessage]
    total_messages: int
    next_offset: int | None
    next_before: int | None = None
    has_more: bool
