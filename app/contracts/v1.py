from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, model_validator

from app.models import AskResponse, DataSource, SourceSchema

Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Source = DataSource


class DatasetSnapshot(BaseModel):
    source_id: Identifier
    snapshot_id: Identifier
    schema_version: int = Field(ge=1)
    content_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    created_at: datetime
    state: Literal['importing', 'ready', 'failed']
    row_count: int | None = Field(default=None, ge=0)


class TopValue(BaseModel):
    value: str
    count: int = Field(ge=0)


class NumericProfile(BaseModel):
    count: int = Field(ge=0)
    minimum: str
    maximum: str
    total: str
    average: str


class TemporalProfile(BaseModel):
    count: int = Field(ge=0)
    minimum: str
    maximum: str


class SampleColumnProfile(BaseModel):
    """Facts calculated only from a bounded sample."""

    model_config = ConfigDict(extra='forbid')
    sample_non_null_count: int = Field(ge=0)
    sample_null_count: int = Field(ge=0)
    distinct_sample_values: int = Field(ge=0)
    top_values: list[TopValue]


class ColumnProfile(SampleColumnProfile):
    """Sample facts plus statistics calculated across an exact snapshot."""

    non_null_count: int = Field(ge=0)
    null_count: int = Field(ge=0)
    empty_count: int = Field(ge=0)
    distinct_count: int = Field(ge=0)
    uniqueness_ratio: float = Field(ge=0, le=1)
    is_identifier_candidate: bool
    top_values_coverage: Literal['sample']
    numeric: NumericProfile | None = None
    temporal: TemporalProfile | None = None


class FullProfile(BaseModel):
    """Profile with exact statistics for an immutable CSV snapshot."""

    model_config = ConfigDict(extra='forbid')
    sample_size: int = Field(ge=0)
    sample_limit: int = Field(ge=1)
    processed_rows: int = Field(ge=0)
    coverage: Literal['full']
    snapshot_id: Identifier
    columns: dict[str, ColumnProfile]
    note: str
    snapshot: DatasetSnapshot | None = None

    @model_validator(mode='after')
    def consistent_exact_statistics(self):
        _validate_sample_statistics(self.sample_size, self.sample_limit, self.columns)
        if self.snapshot and self.snapshot.snapshot_id != self.snapshot_id:
            raise ValueError('profile snapshot_id must match attached snapshot')
        if self.snapshot and self.snapshot.row_count is not None and self.snapshot.row_count != self.processed_rows:
            raise ValueError('profile processed_rows must match attached snapshot row_count')
        for column in self.columns.values():
            if column.non_null_count + column.null_count != self.processed_rows:
                raise ValueError('column null counts must equal processed_rows')
            if column.empty_count > column.non_null_count:
                raise ValueError('column empty_count cannot exceed non_null_count')
            if column.distinct_count > column.non_null_count:
                raise ValueError('column distinct_count cannot exceed non_null_count')
            if column.is_identifier_candidate and not (
                column.non_null_count == self.processed_rows
                and column.empty_count == 0
                and column.distinct_count == self.processed_rows
            ):
                raise ValueError('identifier candidate must be complete and unique')
            typed_count = column.non_null_count - column.empty_count
            if column.numeric and column.temporal:
                raise ValueError('column cannot be numeric and temporal simultaneously')
            if column.numeric and column.numeric.count != typed_count:
                raise ValueError('numeric count must equal non-empty values')
            if column.temporal and column.temporal.count != typed_count:
                raise ValueError('temporal count must equal non-empty values')
        return self


class SampleProfile(BaseModel):
    """Profile whose facts are limited to a bounded live PostgreSQL sample."""

    model_config = ConfigDict(extra='forbid')
    sample_size: int = Field(ge=0)
    sample_limit: int = Field(ge=1)
    coverage: Literal['sample']
    columns: dict[str, SampleColumnProfile]
    note: str

    @model_validator(mode='after')
    def consistent_sample_statistics(self):
        _validate_sample_statistics(self.sample_size, self.sample_limit, self.columns)
        return self


def _validate_sample_statistics(
    sample_size: int,
    sample_limit: int,
    columns: dict[str, SampleColumnProfile],
) -> None:
    if sample_size > sample_limit:
        raise ValueError('sample_size cannot exceed sample_limit')
    for column in columns.values():
        if column.sample_non_null_count + column.sample_null_count != sample_size:
            raise ValueError('sample column counts must equal sample_size')
        if column.distinct_sample_values > column.sample_non_null_count:
            raise ValueError('distinct sample values cannot exceed non-null values')
        if sum(value.count for value in column.top_values) > column.sample_non_null_count:
            raise ValueError('top value counts cannot exceed non-null values')


ProfileVariant = Annotated[FullProfile | SampleProfile, Field(discriminator='coverage')]


class Profile(RootModel[ProfileVariant]):
    """A response that distinguishes exact snapshot facts from sample facts."""

    root: ProfileVariant


class ResultColumn(BaseModel):
    name: Identifier
    data_type: Literal['string', 'integer', 'number', 'decimal', 'boolean', 'date', 'datetime', 'unknown']
    nullable: bool = True


class Provenance(BaseModel):
    source_id: Identifier
    snapshot_id: Identifier
    schema_version: int = Field(ge=1)
    tool_name: Identifier
    executed_at: datetime


class QueryResult(BaseModel):
    result_id: Identifier
    columns: list[ResultColumn]
    rows: list[list[JsonValue]]
    returned_rows: int = Field(ge=0)
    row_limit: int = Field(ge=1, le=10000)
    truncated: bool
    elapsed_ms: float = Field(ge=0, allow_inf_nan=False)
    provenance: list[Provenance] = Field(min_length=1)

    @model_validator(mode='after')
    def consistent_table(self):
        if self.returned_rows != len(self.rows) or self.returned_rows > self.row_limit:
            raise ValueError('returned_rows must equal row count and respect row_limit')
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError('row width must equal column count')
        if len({column.name for column in self.columns}) != len(self.columns):
            raise ValueError('result column names must be unique')
        for row in self.rows:
            for column, value in zip(self.columns, row):
                if value is None and not column.nullable:
                    raise ValueError('null in non-nullable column')
                if column.data_type == 'decimal' and value is not None and not isinstance(value, str):
                    raise ValueError('decimal values must use exact decimal strings')
        return self


class AnalysisPlan(BaseModel):
    intent: str
    sql: str | None = None
    explanation: str


class Error(BaseModel):
    code: Literal['VALIDATION_ERROR', 'SOURCE_NOT_FOUND', 'IMPORT_FAILED', 'QUERY_REJECTED', 'QUERY_TIMEOUT', 'MODEL_UNAVAILABLE', 'INTERNAL_ERROR']
    message: str
    request_id: Identifier
    retryable: bool = False


class AgentResponse(AskResponse):
    contract_version: Literal['1.0'] = '1.0'
    request_id: Identifier
    status: Literal['answered', 'clarification', 'error']
    analysis: AnalysisPlan | None = None
    results: list[QueryResult] = Field(default_factory=list)
    error: Error | None = None
    artifact_ids: list[Identifier] = Field(default_factory=list)
    job_id: Identifier | None = None

    @model_validator(mode='after')
    def consistent_status(self):
        if (self.status == 'error') != (self.error is not None):
            raise ValueError('error status and error payload must agree')
        if self.error and self.error.request_id != self.request_id:
            raise ValueError('error request_id must match response')
        if self.status == 'clarification' and self.results:
            raise ValueError('clarification must not claim executed results')
        return self


CONTRACTS = {'Source': Source, 'SourceSchema': SourceSchema, 'DatasetSnapshot': DatasetSnapshot,
             'Profile': Profile, 'QueryResult': QueryResult, 'AgentResponse': AgentResponse, 'Error': Error}
