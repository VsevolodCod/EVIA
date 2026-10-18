from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_image_builds_frontend_and_starts_http_server() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM node:22-alpine AS frontend-build" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "FROM python:3.12-slim" in dockerfile
    assert "COPY --from=frontend-build" in dockerfile
    assert "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}" in dockerfile


def test_railway_runtime_paths_are_documented() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for setting in (
        "BI_DATA_DIR=/data",
        "CATALOG_DB_PATH=/data/catalog.db",
        "CHAT_DB_PATH=/data/chats.db",
        "/health",
    ):
        assert setting in readme
