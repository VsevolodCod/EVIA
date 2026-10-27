from contextlib import asynccontextmanager
import logging
from uuid import uuid4

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker

from app.agent import AgentRuntime
from app.contracts.v1 import AgentResponse
from app.config import PROJECT_ROOT, get_settings
from app.csv_import import CSVImportError
from app.data_sources.postgresql_adapter import PostgresSourceError, PostgreSQLAdapter
from app.db import create_chat_database, initialize_chat_database, CatalogBase
from app.llm.factory import create_llm_provider
from app.models import AnalysisPayload, AskRequest, AskResponse, ChatMessage, DataSource, CSVVersion, Chat, ChatCreateRequest, ChatSummary, \
    ChatHistoryResponse
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry
from app.core.logging import setup_logging
from app.chat_manager import ChatManager, ChatNotFoundError, ChatSourceConflictError
from app.contracts.v1 import Profile
from app.web import mount_frontend

from app.charts.engine import DashboardEngine
from app.charts.executor import ChartExecutor
from app.charts.repositories import ChartRepository, DashboardRepository

# Логирование и настройки
setup_logging()
logger = logging.getLogger(__name__)

settings = get_settings()

# Каталог источников и схем.
url = URL.create(
    "sqlite+pysqlite",
    database=str(settings.catalog_db_path),
)
engine = create_engine(url)
CatalogBase.metadata.create_all(engine)
session_factory = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)

catalog = SchemaCatalog(settings.catalog_db_path, session_factory)

postgres_adapter = PostgreSQLAdapter(settings.postgres) if settings.postgres.enabled else None

source_service = SourceService(
    settings.data_dir,
    catalog,
    postgres_adapter=postgres_adapter,
)

# Репозитории для REST API.
# Они используют ту же БД и фабрику сессий, что и инструменты агента.
chart_repository = ChartRepository(session_factory)
dashboard_repository = DashboardRepository(session_factory)

dashboard_engine = DashboardEngine(
    charts=chart_repository,
    dashboards=dashboard_repository,
)

# Исполнитель для построения сохранённых чартов.
chart_executor = ChartExecutor.build_executor(
    source_service,
    catalog,
    chart_repository,
)

tool_registry = build_tool_registry(
    catalog=catalog,
    sources=source_service,
    session_factory=session_factory,
)

# LLM и агент
llm_provider = create_llm_provider(settings)

agent = AgentRuntime(
    llm=llm_provider,
    tools=tool_registry,
    max_steps=settings.agent_max_steps,
    sources=source_service,
)


# Жизненный цикл приложения
@asynccontextmanager
async def lifespan(app: FastAPI):
    chat_engine, chat_sessions = create_chat_database(
        settings.chat_db_path
    )

    try:
        await initialize_chat_database(chat_engine)

        if postgres_adapter is not None:
            try:
                source_service.register_postgresql_sources()
            except Exception as exc:
                # Keep CSV usable when the optional remote source is offline.
                logger.warning("PostgreSQL source registration failed: %s", type(exc).__name__)

        # Менеджер получает фабрику асинхронных сессий.
        app.state.chat_manager = ChatManager(chat_sessions)

        logger.info("Application started")
        yield

    finally:
        await chat_engine.dispose()
        catalog.close()
        logger.info("Application stopped")


app = FastAPI(
    title="AI-Native BI Foundation",
    version="0.1.0",
    description="Local-first foundation for an AI-Native BI platform.",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
    }


@app.post("/sources/csv", response_model=DataSource)
async def upload_csv(
        file: UploadFile = File(...),
        name: str | None = Form(default=None),
        source_id: str | None = Form(default=None),
):
    try:
        return await run_in_threadpool(
            source_service.register_csv_stream,
            filename=file.filename or "uploaded.csv",
            stream=file.file,
            name=name,
            source_id=source_id,
        )

    except CSVImportError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": str(exc), "report": exc.report.model_dump(mode="json")},
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("Could not register CSV")
        raise HTTPException(
            status_code=500,
            detail=f"Could not register CSV: {type(exc).__name__}",
        ) from exc


@app.get("/sources", response_model=list[DataSource])
def list_sources():
    return source_service.list_sources()


@app.get("/sources/{source_id}/versions", response_model=list[CSVVersion])
def list_csv_versions(source_id: str):
    try:
        return source_service.list_csv_versions(source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/sources/{source_id}/versions/{snapshot_id}/download")
def download_csv_version(source_id: str, snapshot_id: str):
    try:
        path = source_service.raw_csv_path(source_id, snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="text/csv", filename=path.name)


@app.get("/sources/postgresql/status")
def postgresql_status():
    if postgres_adapter is None:
        return {"configured": False, "connected": False}
    return {"configured": True, "connected": postgres_adapter.connection_status()}


@app.get("/sources/{source_id}/schema")
def get_schema(source_id: str):
    try:
        return source_service.get_schema(source_id)

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.get("/sources/{source_id}/preview")
def preview_source(source_id: str, limit: int = 10):
    try:
        return source_service.preview(source_id, limit)

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.get("/sources/{source_id}/profile", response_model=Profile)
def profile_source(source_id: str):
    try:
        return source_service.profile(source_id)

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except PostgresSourceError as exc:
        status_code, message = {
            "CONNECTION_FAILED": (503, "PostgreSQL source is temporarily unavailable."),
            "QUERY_TIMEOUT": (504, "PostgreSQL source timed out."),
            "INTERNAL_ERROR": (503, "PostgreSQL source is temporarily unavailable."),
            "SOURCE_FORBIDDEN": (403, "PostgreSQL source is not available to this request."),
        }[exc.code]
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": message,
                "retryable": status_code in {503, 504},
            },
        ) from exc


@app.post("/agent/ask", response_model=AgentResponse)
async def ask_agent(body: AskRequest):
    try:
        return await agent.ask(
            question=body.question,
            source_ids=body.source_ids,
            dashboard_id=body.dashboard_id,
        )

    except Exception as exc:
        logger.exception("Agent execution failed")
        raise HTTPException(
            status_code=502,
            detail=f"Agent execution failed: {type(exc).__name__}",
        ) from exc


@app.post("/agent/chat", response_model=AgentResponse)
async def chat_agent(
        body: AskRequest,
        http_request: Request,
        chat_id: str | None = Query(default=None),
        temporary_chat: bool = Query(default=False),
):
    chat_manager: ChatManager = http_request.app.state.chat_manager

    try:
        if len(body.source_ids) > 1 or (not chat_id and not body.source_ids):
            raise ValueError('Select exactly one source before asking in this chat')
        # Получаем существующий чат или создаём новый.
        chat = await chat_manager.get_or_create(
            chat_id=chat_id,
            temporary=temporary_chat,
        )
        logger.info(f"Начат чат с айди {chat.chat_id}")

        selected_source = body.source_ids[0] if body.source_ids else None
        if chat.source_id is None and selected_source is not None and catalog.get_source(selected_source) is None:
            raise HTTPException(status_code=404, detail='Selected source not found')
        chat.source_id = await chat_manager.bind_source(
            chat.chat_id, selected_source, temporary=temporary_chat,
        )

        # Добавляем вопрос пользователя в историю.
        chat.messages.append(
            ChatMessage(
                role="user",
                content=body.question,
            )
        )

        # Сохраняем вопрос до вызова модели.
        # Если агент завершится ошибкой, вопрос не потеряется.
        await chat_manager.save(chat)

        # logger.info("Go into agent.ask")
        # Передаём агенту предыдущую историю без текущего вопроса:
        # текущий вопрос отдельно передаётся через question.
        answer = await agent.ask(
            question=body.question,
            source_ids=[chat.source_id],
            dashboard_id=body.dashboard_id,
            # CSV clarification choices need their persisted structured payload
            # to resume the original request. Providers still receive only
            # role/content fields inside the agent.
            history=chat.messages[:-1],
        )

        response_data = answer.model_dump()
        response_data['chat_id'] = chat.chat_id
        response_data.setdefault('request_id', uuid4().hex)
        response_data.setdefault('status', 'answered')
        response = AgentResponse.model_validate(response_data)

        # Не сохраняем текст ошибки как успешный ответ: незавершённый вопрос
        # при повторном открытии чата остаётся доступным для повтора.
        if response.status != "error":
            chat.messages.append(
                ChatMessage(
                    role="assistant",
                    content=response.answer,
                    analysis_payload=AnalysisPayload(version=1, response=response.model_dump(mode='json')),
                )
            )
            await chat_manager.save(chat)

        # Возвращаем обычный ответ агента вместе с идентификатором чата.
        return response

    except HTTPException:
        raise

    except ChatSourceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    except ChatNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("Chat agent execution failed")
        raise HTTPException(
            status_code=502,
            detail=f"Agent execution failed: {type(exc).__name__}",
        ) from exc


@app.get("/chats", response_model=list[ChatSummary])
async def list_chats(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
):
    chat_manager: ChatManager = request.app.state.chat_manager

    return await chat_manager.list_persistent_chats(
        limit=limit,
        offset=offset,
    )


@app.get("/chats/{chat_id}", response_model=ChatHistoryResponse)
async def get_chat(
        chat_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        before: int | None = Query(default=None, ge=0),
):
    """
    Загружает последние ``limit`` сообщений, заканчивая сообщением номер ``offset`` по айди чата
    :param chat_id: Айди чата
    :param request:
    :param limit: Количество загружаемых сообщений
    :param offset: Номер последнего загруженного сообщения
    :param before:
    :return:
    """
    chat_manager: ChatManager = request.app.state.chat_manager

    if before is not None and offset:
        raise HTTPException(status_code=400, detail='Use before or offset, not both')

    chat = await chat_manager.get_persistent_chat(
        chat_id=chat_id,
        limit=limit,
        offset=offset,
        before=before,
    )

    if chat is None:
        raise HTTPException(
            status_code=404,
            detail=f"Persistent chat '{chat_id}' not found",
        )

    return chat


@app.post("/chats", response_model=ChatSummary, status_code=201)
async def create_chat(
        body: ChatCreateRequest,
        request: Request,
):
    chat_manager: ChatManager = request.app.state.chat_manager

    chat = Chat(
        title=body.title,
        temporary=False,
    )

    await chat_manager.create_persistent_chat(chat)

    return ChatSummary(
        chat_id=chat.chat_id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


@app.delete("/chats/{chat_id}", status_code=204)
async def delete_chat(
        chat_id: str,
        request: Request,
):
    chat_manager: ChatManager = request.app.state.chat_manager

    deleted = await chat_manager.delete(
        chat_id=chat_id,
        temporary=False,
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Persistent chat '{chat_id}' not found",
        )

    return None


# ---------------------------------------------------------------------------
# Dashboards API
# ---------------------------------------------------------------------------

@app.get("/dashboards/ids")
def list_dashboard_ids(
    limit: int = Query(default=100, ge=1, le=500),
):
    """Возвращает ID сохранённых дашбордов."""

    try:
        dashboards = dashboard_repository.list_all(limit=limit)
        return {
            "dashboard_ids": [dashboard.id for dashboard in dashboards],
        }

    except Exception as exc:
        logger.exception("Could not list dashboards")
        raise HTTPException(
            status_code=500,
            detail="Could not list dashboards",
        ) from exc


@app.get("/dashboards/{dashboard_id}")
def get_dashboard_info(dashboard_id: str):
    """Возвращает дашборд и определения сохранённых чартов."""

    result = dashboard_engine.get_dashboard({
        "dashboard_id": dashboard_id,
    })

    if not result.get("success"):
        error = result.get("error") or {}
        code = error.get("code")

        if code == "dashboard_not_found":
            raise HTTPException(
                status_code=404,
                detail="Dashboard not found",
            )

        if code == "invalid_arguments":
            raise HTTPException(
                status_code=400,
                detail="Invalid dashboard ID",
            )

        logger.error("Could not retrieve dashboard: %s", error)
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve dashboard",
        )

    return result


# ---------------------------------------------------------------------------
# Charts API
# ---------------------------------------------------------------------------

@app.get("/charts/{chart_id}")
def get_chart_info(chart_id: str):
    """Возвращает определение сохранённого чарта."""

    try:
        chart = chart_repository.get_by_id(chart_id)

        if chart is None:
            raise HTTPException(
                status_code=404,
                detail="Chart not found",
            )

        return chart.model_dump(mode="json")

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Could not retrieve chart %s", chart_id)
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve chart",
        ) from exc


@app.get("/charts/{chart_id}/build")
def build_saved_chart(chart_id: str):
    """Выполняет сохранённый чарт и возвращает его данные."""

    try:
        chart = chart_repository.get_by_id(chart_id)

        if chart is None:
            raise HTTPException(
                status_code=404,
                detail="Chart not found",
            )

        result = chart_executor.execute(chart_id=chart_id)

        return {
            "success": True,
            "chart_id": chart.id,
            "chart_type": chart.definition.type,
            "definition": chart.definition.model_dump(mode="json"),
            "result": result,
        }

    except HTTPException:
        raise

    except ValueError as exc:
        # Например, чарт не существует или его параметры некорректны.
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("Could not build chart %s", chart_id)
        raise HTTPException(
            status_code=500,
            detail=f"Could not build chart: {type(exc).__name__}",
        ) from exc


@app.get("/dashboards/{dashboard_id}/build")
def build_dashboard(dashboard_id: str):
    """Выполняет все чарты дашборда в порядке их расположения."""

    try:
        dashboard = dashboard_repository.get_by_id(dashboard_id)

        if dashboard is None:
            raise HTTPException(
                status_code=404,
                detail="Dashboard not found",
            )

        chart_results = []

        for ref in sorted(dashboard.charts, key=lambda item: item.position):
            chart = chart_repository.get_by_id(ref.chart_id)

            if chart is None:
                chart_results.append({
                    "chart_id": ref.chart_id,
                    "position": ref.position,
                    "success": False,
                    "error": {
                        "code": "chart_not_found",
                        "message": "Saved chart not found",
                    },
                })
                continue

            try:
                result = chart_executor.execute(
                    chart_id=chart.id,
                )

                chart_results.append({
                    "chart_id": chart.id,
                    "position": ref.position,
                    "success": True,
                    "chart_type": chart.definition.type,
                    "definition": chart.definition.model_dump(mode="json"),
                    "result": result,
                })

            except Exception as exc:
                # Ошибка одного чарта не мешает построить остальные.
                logger.exception(
                    "Could not build chart %s in dashboard %s",
                    ref.chart_id,
                    dashboard_id,
                )

                chart_results.append({
                    "chart_id": ref.chart_id,
                    "position": ref.position,
                    "success": False,
                    "error": {
                        "code": "chart_execution_failed",
                        "message": str(exc),
                    },
                })

        return {
            "success": all(item["success"] for item in chart_results),
            "dashboard": dashboard.model_dump(mode="json"),
            "charts": chart_results,
        }

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Could not build dashboard %s", dashboard_id)
        raise HTTPException(
            status_code=500,
            detail="Could not build dashboard",
        ) from exc



# Register last: the UI must never shadow the API or its documentation.
mount_frontend(app, PROJECT_ROOT / "frontend" / "dist")
