from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.agent import AgentRuntime
from app.config import get_settings
from app.llm.factory import create_llm_provider
from app.models import AskRequest, AskResponse, DataSource
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


settings = get_settings()

catalog = SchemaCatalog(settings.catalog_db)

source_service = SourceService(
    settings.data_dir,
    catalog,
)

tool_registry = build_tool_registry(
    catalog,
    source_service,
)

llm_provider = create_llm_provider(settings)

agent = AgentRuntime(
    llm=llm_provider,
    tools=tool_registry,
    max_steps=settings.agent_max_steps,
)

app = FastAPI(
    title="AI-Native BI Foundation",
    version="0.1.0",
    description="Local-first foundation for an AI-Native BI platform.",
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
async def ask_agent(request: AskRequest):
    try:
        return await agent.ask(
            question=request.question,
            source_ids=request.source_ids,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Agent execution failed: {type(exc).__name__}",
        ) from exc
