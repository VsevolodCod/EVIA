"""Build a small dashboard draft from one selected source and compute it on the server."""

from __future__ import annotations

import json
from time import perf_counter

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.contracts.v1 import AgentResponse, Error
from app.data_sources.postgresql_adapter import PostgresSourceError
from app.llm.base import LLMProvider
from app.models import AgentTiming, ChatMessage, LLMMessage, ModelTiming, ToolResult
from app.source_service import SourceService
from app.tools.base import ToolRegistry


class DraftCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(pattern="^(kpi|line)$")
    title: str = Field(min_length=1, max_length=120)
    field: str | None = None
    x: str | None = None
    y: str | None = None
    aggregate: str = Field(pattern="^(count|sum|avg|min|max)$")

    @model_validator(mode="after")
    def required_fields(self):
        if self.type == "kpi" and not self.field:
            raise ValueError("KPI needs field")
        if self.type == "line" and (not self.x or not self.y):
            raise ValueError("Line needs x and y")
        return self


class DashboardDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    cards: list[DraftCard] = Field(min_length=1, max_length=2)


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
            "Верни только JSON с title и cards. Типы: kpi (field, aggregate) или "
            "line (x, y, aggregate). Агрегации: count, sum, avg, min, max. "
            "Для sum/avg бери числовое поле; для line x — поле группировки, "
            "а y — числовой показатель (кроме count). "
            "Не придумывай результаты, SQL, source_id и дополнительные поля. "
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

            if response.finish_reason != "stop":
                if attempt == 0:
                    messages.append(LLMMessage(role="user", content="Ответ оборвался. Верни короткий полный JSON для одной карточки."))
                    continue
                return self._error(request_id, timing, attempt + 1, trace, "MODEL_OUTPUT_INCOMPLETE")
            try:
                draft = DashboardDraft.model_validate(json.loads(response.content))
            except (ValueError, ValidationError):
                if attempt == 0:
                    messages.append(LLMMessage(role="user", content="Неверный JSON. Верни только title и cards с 1–2 карточками по схеме."))
                    continue
                return self._error(request_id, timing, attempt + 1, trace, "VALIDATION_ERROR")

            if any(field not in field_names for card in draft.cards
                   for field in (card.field, card.x, card.y) if field is not None):
                if attempt == 0:
                    messages.append(LLMMessage(role="user", content="Используй только точные имена доступных полей. Верни JSON заново."))
                    continue
                return self._error(request_id, timing, attempt + 1, trace, "VALIDATION_ERROR")

            chart_ids = []
            cards = []
            rendered_cards = []
            for index, card in enumerate(draft.cards):
                definition = {"type": card.type, "title": card.title}
                if card.type == "kpi":
                    definition.update({
                        "field": {"source_id": source_id, "field": card.field},
                        "aggregate": card.aggregate,
                    })
                else:
                    x_field = next(field for field in fields if field.name == card.x)
                    definition.update({
                        "x": {
                            "source_id": source_id, "field": card.x,
                            "type": "temporal" if x_field.inferred_type in {"date", "datetime"} else "category",
                        },
                        "y": {
                            "source_id": source_id, "field": card.y,
                            "aggregate": card.aggregate,
                        },
                    })
                chart_started = perf_counter()
                built = self.tools.execute("build_chart", {"definition": definition, "filters": []})
                timing.tools_ms += (perf_counter() - chart_started) * 1000
                trace.append(built)
                if built.ok and isinstance(built.data, dict) and built.data.get("success"):
                    chart_id = built.data.get("chart_id")
                    if isinstance(chart_id, str):
                        chart_ids.append(chart_id)
                        cards.append(card)
                        rendered_cards.append({
                            "id": chart_id,
                            "type": card.type,
                            "title": card.title,
                            "status": "success",
                            "data": built.data.get("result"),
                        })
            started = perf_counter()
            result = self.tools.execute("compose_dashboard", {
                "title": draft.title, "summary": None, "chart_ids": chart_ids,
            })
            timing.tools_ms += (perf_counter() - started) * 1000
            trace.append(result)
            successful = result.ok and isinstance(result.data, dict) and result.data.get("success") is True
            if successful:
                count = len(chart_ids)
                failed = len(draft.cards) - count
                dashboard = result.data.get("dashboard")
                trace.append(ToolResult(tool_name="create_dashboard", ok=True, data={
                    "version": 1,
                    "id": dashboard.get("id") if isinstance(dashboard, dict) else None,
                    "title": draft.title,
                    "cards": rendered_cards,
                }))
                answer = f"Построено карточек: {count}."
                if failed:
                    answer += f" Не удалось рассчитать: {failed}."
                return AgentResponse(
                    request_id=request_id, status="answered", answer=answer,
                    answer_kind="computed", steps=attempt + 1, tool_results=trace,
                    timing=timing,
                )
            if attempt == 0:
                messages.append(LLMMessage(role="user", content="Карточка не рассчиталась. Выбери одну простую карточку по типу поля и верни JSON заново."))
                continue
            return self._error(request_id, timing, attempt + 1, trace, "QUERY_REJECTED")
        return self._error(request_id, timing, 2, trace, "QUERY_REJECTED")

    @staticmethod
    def _error(request_id, timing, steps, trace, code):
        message = "Не удалось построить дашборд по выбранному источнику. Попробуйте уточнить поля и показатель."
        return AgentResponse(
            request_id=request_id, status="error", answer=message, steps=steps,
            tool_results=trace, timing=timing,
            error=Error(code=code, message=message, request_id=request_id,
                        retryable=code not in {"SOURCE_NOT_FOUND", "VALIDATION_ERROR"}),
        )
