"""Persist executed analysis and apply explicit, validated continuation edits."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import sqlglot
from sqlglot import exp

from app.charts.aggregation import filter_expression, quote_identifier
from app.charts.models import Aggregate, DashboardFilter, FilterOperator, TimeGrain
from app.contracts.v1 import CalculationContext, QueryResult
from app.models import ChatMessage, LLMMessage
from app.tools.base import ToolDefinition, ToolRegistry

MAX_CONTEXT_CHARS = 16000
MAX_HISTORY_CHARS = 12000
MAX_MESSAGE_CHARS = 2000


def _and_parts(node):
    if node is None:
        return []
    if isinstance(node, exp.Paren):
        return _and_parts(node.this)
    if isinstance(node, exp.And):
        return [*_and_parts(node.this), *_and_parts(node.expression)]
    return [node]


def context_from_query(sql: str, result: QueryResult, presentation='table') -> CalculationContext | None:
    """The query already passed the SQL guard and executed successfully."""
    try:
        tree = sqlglot.parse_one(sql, read='duckdb')
        if not isinstance(tree, exp.Select) or len(result.provenance) != 1:
            return None
        provenance = result.provenance[0]
        where = tree.args.get('where')
        group = tree.args.get('group')
        return CalculationContext(
            source_id=provenance.source_id, snapshot_id=provenance.snapshot_id,
            schema_version=provenance.schema_version, result_id=result.result_id, sql=sql,
            metrics=[item.sql(dialect='duckdb') for item in tree.expressions if item.find(exp.AggFunc)],
            dimensions=[item.sql(dialect='duckdb') for item in group.expressions] if group else [],
            filters=[item.sql(dialect='duckdb') for item in _and_parts(where.this if where else None)],
            presentation=presentation,
        )
    except (ValueError, sqlglot.errors.ParseError):
        return None


def _payload(message):
    if message.role != 'assistant':
        return None
    saved = getattr(message, 'analysis_payload', None)
    if saved and saved.version == 1:
        return saved.response
    return getattr(message, 'response', None)


def restore_context(history: list[ChatMessage], selected, sources):
    """Read the latest server snapshot. A stale marker is a reset barrier."""
    contexts = []
    barrier = 0
    for index in range(len(history) - 1, -1, -1):
        payload = _payload(history[index])
        if isinstance(payload, dict) and payload.get('context_status') == 'stale':
            barrier = index + 1
            break
    for index in range(len(history) - 1, barrier - 1, -1):
        payload = _payload(history[index])
        if not isinstance(payload, dict):
            continue
        if 'analysis_contexts' in payload and payload.get('context_status') == 'none':
            break
        if payload.get('analysis_contexts'):
            try:
                contexts = [CalculationContext.model_validate(item) for item in payload['analysis_contexts']]
                if len(contexts) > 8 or len(json.dumps([c.model_dump(mode='json') for c in contexts], ensure_ascii=False)) > MAX_CONTEXT_CHARS:
                    return [], {}, 'stale', []
            except (ValidationError, TypeError):
                return [], {}, 'stale', []
            break
    if contexts and (selected is None or any(
        c.source_id != selected.source_id or c.snapshot_id != (selected.snapshot_id or 'legacy')
        or c.schema_version != selected.schema_version for c in contexts
    )):
        return [], {}, 'stale', []
    results = {}
    ids = {c.result_id for c in contexts}
    for message in reversed(history[barrier:]):
        payload = _payload(message)
        if not isinstance(payload, dict):
            continue
        for raw in payload.get('results') or []:
            try:
                result = QueryResult.model_validate(raw)
                if result.result_id in ids:
                    results.setdefault(result.result_id, result)
            except (ValidationError, TypeError):
                continue
    return contexts, results, 'active' if contexts else 'none', history[barrier:]


def bounded_history(history):
    """Keep recent text; calculated parameters live outside this text budget."""
    kept, remaining = [], MAX_HISTORY_CHARS
    for item in reversed(history[-12:]):
        if item.role not in {'user', 'assistant'} or remaining <= 0:
            continue
        content = item.content[:min(MAX_MESSAGE_CHARS, remaining)]
        kept.append(LLMMessage(role=item.role, content=content))
        remaining -= len(content)
    return list(reversed(kept))


class EditFilter(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    field: str = Field(min_length=1, max_length=200)
    operator: FilterOperator
    value: str | int | float | bool | list[str | int | float | bool] | None = None
    date_part: Literal['month', 'quarter', 'year'] | None = None

    @model_validator(mode='after')
    def valid_value(self):
        DashboardFilter(field={'source_id': 'selected', 'field': self.field}, operator=self.operator, value=self.value)
        if isinstance(self.value, list) and self.operator not in {'between', 'in', 'not_in'}:
            raise ValueError('Scalar filter requires a scalar value')
        return self


class ContinueArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    result_id: str | None = None
    group_by: list[str] | None = Field(default=None, max_length=8)
    time_field: str | None = None
    time_grain: TimeGrain | None = None
    add_filters: list[EditFilter] = Field(default_factory=list, max_length=20)
    remove_filter_indexes: list[int] = Field(default_factory=list, max_length=40)
    measure_field: str | None = None
    aggregate: Aggregate | None = None
    presentation: Literal['table', 'bar', 'line'] | None = None


def _simple_select(sql):
    tree = sqlglot.parse_one(sql, read='duckdb')
    tables = list(tree.find_all(exp.Table))
    if (not isinstance(tree, exp.Select) or len(tables) != 1 or tables[0].alias
        or tables[0].name not in {'source', 'source_typed'} or tree.args.get('with_')
        or tree.args.get('joins') or tree.args.get('having') or tree.args.get('distinct')
        or tree.find(exp.Subquery) or tree.find(exp.Window)):
        raise ValueError('Complex query needs a new explicit analysis')
    return tree


def continuation_sql(context, args, schema):
    tree = _simple_select(context.sql)
    fields = {f.name: f for obj in schema.objects for f in obj.fields}
    names = [*(args.group_by or []), *(f.field for f in args.add_filters)]
    names += [name for name in [args.time_field, args.measure_field] if name]
    if any(name not in fields for name in names):
        raise ValueError('Unknown field')
    if len(args.group_by or []) != len(set(args.group_by or [])):
        raise ValueError('Duplicate dimensions')
    if bool(args.time_field) != bool(args.time_grain) or bool(args.measure_field) != bool(args.aggregate):
        raise ValueError('Incomplete date or metric edit')
    if args.time_field and fields[args.time_field].inferred_type not in {'date', 'datetime', 'timestamp'}:
        raise ValueError('Time grouping needs a date field')
    if args.measure_field:
        if args.aggregate in {'sum', 'avg'} and fields[args.measure_field].inferred_type not in {'integer', 'number', 'decimal'}:
            raise ValueError('Numeric metric required')
        metric = 'COUNT(*)' if args.aggregate == 'count' else f'{args.aggregate.upper()}({quote_identifier(args.measure_field)})'
        metrics = [sqlglot.parse_one(metric+' AS value', read='duckdb')]
    else:
        metrics = [item.copy() for item in tree.expressions if item.find(exp.AggFunc)]
    regroup = args.group_by is not None or args.time_field is not None
    if regroup or args.measure_field:
        if not metrics:
            raise ValueError('No unambiguous aggregate to continue')
        existing_group = tree.args.get('group')
        groups = [item.copy() for item in existing_group.expressions] if existing_group else []
        if args.group_by is not None:
            groups = [exp.column(name, quoted=True) for name in args.group_by]
        if args.time_field:
            groups = [sqlglot.parse_one(f"DATE_TRUNC('{args.time_grain}', {quote_identifier(args.time_field)})", read='duckdb'),
                      *[item for item in groups if not item.find(exp.TimestampTrunc) and not item.find(exp.DateTrunc)]]
        projections = [item.copy().as_(f'group_{index+1}') for index, item in enumerate(groups)]
        tree.set('expressions', [*projections, *metrics])
        tree.set('group', exp.Group(expressions=groups) if groups else None)
        tree.set('order', exp.Order(expressions=[exp.Ordered(this=item.copy()) for item in groups]) if groups else None)
    old_where = tree.args.get('where')
    filters = _and_parts(old_where.this if old_where else None)
    if any(index < 0 or index >= len(filters) for index in args.remove_filter_indexes):
        raise ValueError('Unknown filter index')
    filters = [item for index, item in enumerate(filters) if index not in args.remove_filter_indexes]
    for item in args.add_filters:
        model = DashboardFilter(field={'source_id': context.source_id, 'field': item.field}, operator=item.operator, value=item.value)
        expression = filter_expression(model)
        if item.date_part:
            if fields[item.field].inferred_type not in {'date', 'datetime', 'timestamp'}:
                raise ValueError('Date part needs a date field')
            name = quote_identifier(item.field)
            expression = f'EXTRACT({item.date_part.upper()} FROM {name})'+expression[len(name):]
        filters.append(sqlglot.parse_one(expression, read='duckdb'))
    condition = exp.and_(*[item.copy() for item in filters]) if filters else None
    tree.set('where', exp.Where(this=condition) if condition is not None else None)
    return tree.sql(dialect='duckdb')


class ContextSession:
    """Mutable only inside one ask call; never stored on AgentRuntime."""
    def __init__(self, sources, contexts, results):
        self.sources = sources
        self.contexts = list(contexts)
        self.results = dict(results)
        self.executed = []

    def record(self, sql, result, presentation='table'):
        context = context_from_query(sql, result, presentation)
        if not self.executed:
            self.contexts = []
        if context is None:
            self.contexts = []
            self.executed = []
            return
        if context:
            # A new query begins a new active calculation. Multiple successful
            # queries within this request remain explicit alternatives.
            self.executed.append(context)
            self.contexts = self.executed[-8:]
            if len(json.dumps([c.model_dump(mode='json') for c in self.contexts], ensure_ascii=False)) > MAX_CONTEXT_CHARS:
                self.contexts = []
                self.executed = []
                return
            self.results[result.result_id] = result

    def register(self, registry: ToolRegistry):
        schema = ContinueArgs.model_json_schema()
        # Schema is nonrecursive; inline local refs for existing tool adapters.
        from app.tools.charts import _resolve_refs
        definitions = schema.pop('$defs', {})
        properties = _resolve_refs(schema['properties'], definitions)
        registry.register(ToolDefinition(
            name='continue_analysis',
            description=(
                'Continue an executed calculation from analysis_contexts. Omit edits to preserve the metric and filters. '
                'Use time_field/time_grain for calendar groups, group_by for dimensions; an empty group_by removes dimensions. '
                'add_filters appends AND conditions; remove_filter_indexes removes ONLY explicitly changed conditions by zero-based index. '
                'date_part=month with ne 7 excludes July. measure_field+aggregate explicitly changes the metric. '
                'presentation changes table/bar/line; a view-only change reuses the saved result when available. '
                'If several result_ids exist, ask which one rather than guessing. Use query_data for an explicitly new analysis.'
            ), parameters=properties, required=[], handler=self.continue_analysis,
        ))

    def continue_analysis(self, **payload):
        try:
            args = ContinueArgs.model_validate(payload)
            matches = [c for c in self.contexts if args.result_id is None or c.result_id == args.result_id]
            if len(matches) != 1:
                return {'error': 'CONTEXT_AMBIGUOUS', 'message': 'Уточните, какой из предыдущих расчётов продолжить.'}
            context = matches[0]
            source = self.sources.catalog.get_source(context.source_id)
            if not source or (source.snapshot_id or 'legacy') != context.snapshot_id or source.schema_version != context.schema_version:
                return {'error': 'CONTEXT_STALE', 'message': 'Данные изменились. Начните новый расчёт для текущей версии.'}
            presentation = args.presentation or context.presentation
            edits = args.model_dump(exclude={'result_id', 'presentation'}, exclude_none=True)
            changed = any(value not in ([], None) for value in edits.values()) or args.group_by == []
            result = self.results.get(context.result_id)
            sql = context.sql
            if changed or result is None:
                sql = continuation_sql(context, args, self.sources.get_schema(context.source_id))
                result = self.sources.query(context.source_id, sql)
                if any(p.snapshot_id != context.snapshot_id or p.schema_version != context.schema_version for p in result.provenance):
                    return {'error': 'CONTEXT_STALE', 'message': 'Данные изменились во время расчёта. Повторите новый анализ.'}
            self.record(sql, result, presentation)
            return {'query_result': result.model_dump(mode='json'), 'presentation': presentation,
                    'reused_result': not changed and result.result_id == context.result_id}
        except (ValueError, TypeError, sqlglot.errors.ParseError):
            return {'error': 'CONTEXT_EDIT_REJECTED', 'message': 'Не удалось однозначно применить изменение. Уточните поле, показатель или условие.'}
