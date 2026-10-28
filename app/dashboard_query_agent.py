"""Build a small dashboard draft from one selected source and compute it on the server."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Literal

import httpx
from pydantic import (
    BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr,
    ValidationError, model_validator,
)

from app.charts.models import DashboardFilter, FilterOperator, TimeGrain

from app.contracts.v1 import AgentResponse, Error
from app.data_sources.postgresql_adapter import PostgresSourceError
from app.llm.base import LLMProvider
from app.models import AgentTiming, ChatMessage, LLMMessage, ModelTiming, ToolResult
from app.source_service import SourceService
from app.tools.base import ToolRegistry


FilterScalar = StrictStr | StrictInt | StrictFloat | StrictBool


class DraftFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    field: str = Field(min_length=1, max_length=200)
    operator: FilterOperator
    value: FilterScalar | list[FilterScalar] | None = None

    @model_validator(mode="after")
    def valid_filter(self):
        DashboardFilter(field={"source_id": "selected", "field": self.field},
                        operator=self.operator, value=self.value)
        if isinstance(self.value, list) and self.operator not in {"in", "not_in", "between"}:
            raise ValueError("A scalar comparison cannot contain a list")
        return self


class DraftCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["kpi", "line", "bar", "scatter", "table"]
    title: str = Field(min_length=1, max_length=120)
    field: str | None = None
    x: str | None = None
    y: str | None = None
    aggregate: Literal["count", "sum", "avg", "min", "max"] | None = None
    time_grain: TimeGrain | None = None
    fields: list[str] | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def required_fields(self):
        if self.type == "kpi" and (not self.field or not self.aggregate or self.x or self.y or self.fields or self.time_grain):
            raise ValueError("KPI needs only a field and aggregate")
        if self.type in {"line", "bar"} and (not self.x or not self.y or not self.aggregate or self.field or self.fields):
            raise ValueError("Grouped chart needs x, y and aggregate")
        if self.type == "scatter" and (not self.x or not self.y or self.field or self.fields or self.aggregate or self.time_grain):
            raise ValueError("Scatter needs only numeric x and y fields")
        if self.type == "table" and (not self.fields or self.field or self.x or self.y or self.aggregate or self.time_grain):
            raise ValueError("Table needs only selected fields")
        if self.type not in {"line", "bar"} and self.time_grain is not None:
            raise ValueError("Only grouped charts support time_grain")
        return self


class DashboardDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    # Required even when empty: an old/incomplete plan must not silently lose
    # the user's constraints. source_id is always bound by the server.
    filters: list[DraftFilter] = Field(max_length=20)
    cards: list[DraftCard] = Field(max_length=2)
    clarification: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def cards_or_clarification(self):
        if bool(self.cards) == bool(self.clarification):
            raise ValueError("Return either cards or a clarification, never both")
        return self


def is_dashboard_question(question: str) -> bool:
    words = question.casefold()
    return any(marker in words for marker in (
        "дашборд", "график", "диаграмм", "визуализ", "kpi", "кпи", "dashboard", "chart",
    ))


class DashboardQueryAgent:
    def __init__(self, llm: LLMProvider, sources: SourceService, tools: ToolRegistry) -> None:
        self.llm = llm
        self.sources = sources
        self.tools = tools

    async def ask(
        self, question: str, source_id: str, timing: AgentTiming, request_id: str,
        history: list[ChatMessage] | None = None,
    ) -> AgentResponse:
        try:
            schema = self.sources.get_schema(source_id)
        except KeyError:
            return self._error(request_id, timing, 0, [], "SOURCE_NOT_FOUND")
        except (ValueError, PostgresSourceError):
            return self._error(request_id, timing, 0, [], "INTERNAL_ERROR")
        fields = schema.objects[0].fields if schema.objects else []
        field_names = {field.name for field in fields}
        columns = ", ".join(f'"{field.name}" ({field.inferred_type})' for field in fields)
        system = (
            "Выбери от одной до двух карточек для дашборда из реальных полей источника. "
            "Верни только JSON с title, filters, cards и clarification (null при успехе). "
            "filters обязателен: все условия вопроса, применённые ко ВСЕМ карточкам через AND; "
            "каждый фильтр: {field, operator, value}. Операторы eq/ne/gt/gte/lt/lte/in/not_in/"
            "between/is_null/is_not_null. Для чисел value — число, для даты — ISO-строка. "
            "Период по полю даты выражай фильтрами gte начала и lt следующей границы "
            "(например за 2025 год: >= 2025-01-01, < 2026-01-01). "
            "Не угадывай дату для относительных периодов, если она не определена в запросе/контексте. "
            "Типы: kpi (field, aggregate), line/bar (x, y, aggregate, time_grain), "
            "scatter (x, y: два числовых поля, без aggregate), "
            "table (fields: список существующих полей, без aggregate). "
            "Выбирай line для времени, bar для категорий, scatter для связи двух чисел, "
            "table для отдельных строк или когда график невозможен. "
            "time_grain: day/week/month/quarter/year "
            "для группировки по настоящему полю даты; null — исходные значения. "
            "Не подменяй кварталы месяцами/датами, не суммируй идентификаторы. "
            "Агрегации: count, sum, avg, min, max. "
            "Для sum/avg бери числовое поле; для line/bar x — поле группировки, "
            "а y — числовой показатель (кроме count). "
            "Не придумывай результаты, SQL, source_id и дополнительные поля. "
            "Сохраняй показатель, фильтры и период при продолжении диалога, если пользователь "
            "их не меняет. Если поле отсутствует, условие неоднозначно или его нельзя выразить "
            "этим контрактом (например OR между разными полями), верни cards=[], filters=[] "
            "и clarification с конкретным вопросом. Не заменяй запрос общим обзором. "
            f"Доступные поля: {columns}."
        )
        context = [LLMMessage(role=item.role, content=item.content[:1000])
                   for item in (history or [])[-4:] if item.role in {"user", "assistant"}]
        messages = [LLMMessage(role="system", content=system), *context,
                    LLMMessage(role="user", content=question)]
        trace: list[ToolResult] = []
        for attempt in range(2):
            started = perf_counter()
            try:
                structured_chat = getattr(self.llm, "chat_structured", None)
                response = (
                    await structured_chat(messages, DashboardDraft.model_json_schema())
                    if structured_chat is not None else await self.llm.chat(messages)
                )
            except (httpx.HTTPError, TimeoutError):
                elapsed = (perf_counter() - started) * 1000
                timing.llm_ms += elapsed
                timing.calls.append(ModelTiming(elapsed_ms=elapsed))
                return self._error(request_id, timing, attempt + 1, trace, "MODEL_UNAVAILABLE")
            elapsed = (perf_counter() - started) * 1000
            timing.llm_ms += elapsed
            call_timing = response.timing.model_copy() if response.timing else ModelTiming()
            call_timing.elapsed_ms = elapsed
            timing.calls.append(call_timing)

            draft: DashboardDraft | None = None
            if response.finish_reason == "stop":
                try:
                    candidate = DashboardDraft.model_validate(json.loads(response.content))
                except (ValueError, ValidationError):
                    candidate = None
                if candidate and not any(
                    field not in field_names for card in candidate.cards
                    for field in (card.field, card.x, card.y, *(card.fields or [])) if field is not None
                ) and not any(item.field not in field_names for item in candidate.filters):
                    draft = candidate

            if draft is None:
                if attempt == 0:
                    messages.append(LLMMessage(role="user", content=(
                        "План неполный или не соответствует схеме. Верни полный JSON с title, "
                        "filters, cards, clarification. Сохрани ВСЕ условия исходного вопроса. "
                        "Если они невыполнимы, верни cards=[] и конкретное clarification."
                    )))
                    continue
                return self._clarification(request_id, timing, attempt + 1,
                    "Не удалось составить проверяемый план дашборда с условиями запроса. "
                    "Уточните показатель, поле даты, период и фильтры. Дашборд не создан.")

            if draft.clarification:
                return self._clarification(request_id, timing, attempt + 1, draft.clarification)

            filters = [{"field": {"source_id": source_id, "field": item.field},
                        "operator": item.operator, "value": item.value} for item in draft.filters]
            chart_ids = []
            rendered_cards = []
            for card in draft.cards:
                definition = {"type": card.type, "title": card.title, "filters": filters}
                if card.type == "kpi":
                    definition.update({
                        "field": {"source_id": source_id, "field": card.field},
                        "aggregate": card.aggregate,
                    })
                elif card.type in {"line", "bar"}:
                    x_field = next(field for field in fields if field.name == card.x)
                    definition.update({
                        "x": {
                            "source_id": source_id, "field": card.x,
                            "type": "temporal" if x_field.inferred_type in {"date", "datetime", "timestamp"} else "category",
                            "time_grain": card.time_grain,
                        },
                        "y": {
                            "source_id": source_id, "field": card.y,
                            "aggregate": card.aggregate,
                        },
                    })
                elif card.type == "scatter":
                    definition.update({
                        "x": {"source_id": source_id, "field": card.x},
                        "y": {"source_id": source_id, "field": card.y},
                    })
                else:
                    definition["fields"] = [
                        {"source_id": source_id, "field": name} for name in (card.fields or [])
                    ]
                chart_started = perf_counter()
                built = self.tools.execute("build_chart", {"definition": definition, "filters": []})
                timing.tools_ms += (perf_counter() - chart_started) * 1000
                if built.ok and isinstance(built.data, dict) and built.data.get("success"):
                    chart_id = built.data.get("chart_id")
                    if isinstance(chart_id, str):
                        chart_ids.append(chart_id)
                        rendered_cards.append({
                            "id": chart_id,
                            "type": card.type,
                            "title": card.title,
                            "status": "success",
                            "definition": built.data.get("definition"),
                            "data": built.data.get("result"),
                        })
                    continue
                rendered_cards.append({
                    "id": f"failed-{len(rendered_cards) + 1}",
                    "type": card.type,
                    "title": card.title,
                    "status": "error",
                    "error": {
                        "code": "chart_execution_failed",
                        "message": "Не удалось построить график по выбранным полям.",
                    },
                })

            composed = False
            dashboard_id = None
            if chart_ids:
                started = perf_counter()
                result = self.tools.execute("compose_dashboard", {
                    "title": draft.title, "summary": None, "chart_ids": chart_ids,
                })
                timing.tools_ms += (perf_counter() - started) * 1000
                composed = (
                    result.ok
                    and isinstance(result.data, dict)
                    and result.data.get("success") is True
                )
                if composed and isinstance(result.data.get("dashboard"), dict):
                    dashboard_id = result.data["dashboard"].get("id")

            # Keep the UI/API contract stable: callers receive one dashboard
            # result per model attempt, not implementation-specific tool steps.
            trace.append(ToolResult(tool_name="create_dashboard", ok=True, data={
                "version": 1,
                "id": dashboard_id,
                "title": draft.title,
                "cards": rendered_cards,
            }))
            successful = composed and any(
                item["status"] == "success" for item in rendered_cards
            )
            if successful:
                count = len(chart_ids)
                failed = len(draft.cards) - count
                answer = f"Построено карточек: {count}."
                if failed:
                    answer += f" Не удалось рассчитать: {failed}."
                return AgentResponse(
                    request_id=request_id, status="answered", answer=answer,
                    answer_kind="computed", steps=attempt + 1, tool_results=trace,
                    timing=timing,
                )
            # An execution failure must not trigger a simpler, unfiltered plan
            # which changes the question. Preserve the failed cards for the UI.
            return self._error(request_id, timing, attempt + 1, trace, "QUERY_REJECTED")
        return self._error(request_id, timing, 2, trace, "QUERY_REJECTED")

    @staticmethod
    def _clarification(request_id, timing, steps, message):
        return AgentResponse(request_id=request_id, status="clarification",
                             outcome="clarification", answer=message, steps=steps,
                             tool_results=[], timing=timing)

    @staticmethod
    def _error(request_id, timing, steps, trace, code):
        message = "Не удалось построить дашборд по выбранному источнику. Попробуйте уточнить поля и показатель."
        return AgentResponse(
            request_id=request_id, status="error", answer=message, steps=steps,
            tool_results=trace, timing=timing,
            error=Error(code=code, message=message, request_id=request_id,
                        retryable=code not in {"SOURCE_NOT_FOUND", "VALIDATION_ERROR"}),
        )
