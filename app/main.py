from contextlib import asynccontextmanager
import logging

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

from app.agent import AgentRuntime
from app.config import PROJECT_ROOT, get_settings
from app.csv_import import CSVImportError
from app.data_sources.postgresql_adapter import PostgresSourceError, PostgreSQLAdapter
from app.db import create_chat_database, initialize_chat_database
from app.llm.factory import create_llm_provider
from app.models import AskRequest, AskResponse, ChatMessage, DataSource, CSVVersion, Chat, ChatCreateRequest, ChatSummary, \
    ChatHistoryResponse
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry
from app.core.logging import setup_logging
from app.chat_manager import ChatManager, ChatNotFoundError
from app.contracts.v1 import Profile
from app.web import mount_frontend


# Логирование и настройки
setup_logging()
logger = logging.getLogger(__name__)

settings = get_settings()


# Каталог источников и схем.
# SchemaCatalog самостоятельно создаёт синхронный SQLAlchemy engine.
catalog = SchemaCatalog(settings.catalog_db_path)

postgres_adapter = PostgreSQLAdapter(settings.postgres) if settings.postgres.enabled else None

source_service = SourceService(
    settings.data_dir,
    catalog,
    postgres_adapter=postgres_adapter,
)

tool_registry = build_tool_registry(
    catalog,
    source_service,
)


# LLM и агент
llm_provider = create_llm_provider(settings)

agent = AgentRuntime(
    llm=llm_provider,
    tools=tool_registry,
    max_steps=settings.agent_max_steps,
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


@app.post("/agent/ask", response_model=AskResponse)
async def ask_agent(body: AskRequest):
    try:
        return await agent.ask(
            question=body.question,
            source_ids=body.source_ids,
        )

    except Exception as exc:
        logger.exception("Agent execution failed")
        raise HTTPException(
            status_code=502,
            detail=f"Agent execution failed: {type(exc).__name__}",
        ) from exc


@app.post("/agent/chat", response_model=AskResponse)
async def chat_agent(
    body: AskRequest,
    http_request: Request,
    chat_id: str | None = Query(default=None),
    temporary_chat: bool = Query(default=False),
):
    chat_manager: ChatManager = http_request.app.state.chat_manager

    try:
        # Получаем существующий чат или создаём новый.
        chat = await chat_manager.get_or_create(
            chat_id=chat_id,
            temporary=temporary_chat,
        )
        logger.info(f"Начат чат с айди {chat.chat_id}")

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

        # Передаём агенту предыдущую историю без текущего вопроса:
        # текущий вопрос отдельно передаётся через question.
        answer = await agent.ask(
            question=body.question,
            source_ids=body.source_ids,
            history=chat.messages[:-1],
        )

        # Сохраняем ответ ассистента в истории.
        chat.messages.append(
            ChatMessage(
                role="assistant",
                content=answer.answer,
            )
        )

        await chat_manager.save(chat)

        # Возвращаем обычный ответ агента вместе с идентификатором чата.
        response_data = answer.model_dump()
        response_data["chat_id"] = chat.chat_id
        return AskResponse.model_validate(response_data)

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


# Register last: the UI must never shadow the API or its documentation.
mount_frontend(app, PROJECT_ROOT / "frontend" / "dist")
