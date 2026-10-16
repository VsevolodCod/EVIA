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

from app.agent import AgentRuntime
from app.config import get_settings
from app.db import create_chat_database, initialize_chat_database
from app.llm.factory import create_llm_provider
from app.models import AskRequest, AskResponse, ChatMessage, DataSource, Chat, ChatCreateRequest, ChatSummary, \
    ChatHistoryResponse
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry
from app.core.logging import setup_logging
from app.chat_manager import ChatManager, ChatNotFoundError


# Логирование и настройки
setup_logging()
logger = logging.getLogger(__name__)

settings = get_settings()


# Каталог источников и схем.
# SchemaCatalog самостоятельно создаёт синхронный SQLAlchemy engine.
catalog = SchemaCatalog(settings.catalog_db_path)

source_service = SourceService(
    settings.data_dir,
    catalog,
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
):
    try:
        content = await file.read()

        return source_service.register_csv(
            filename=file.filename or "uploaded.csv",
            content=content,
            name=name,
        )

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
    return catalog.list_sources()


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


@app.get("/sources/{source_id}/profile")
def profile_source(source_id: str):
    try:
        return source_service.profile(source_id)

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
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

    chat = await chat_manager.get_persistent_chat(
        chat_id=chat_id,
        limit=limit,
        offset=offset,
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


