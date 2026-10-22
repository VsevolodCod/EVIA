"""HTTP contract for import reports and immutable CSV snapshots."""

import importlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


@pytest.mark.asyncio
async def test_http_import_report_error_and_reimport_versions(tmp_path, monkeypatch):
    module = importlib.import_module("app.main")
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    service = SourceService(tmp_path / "data", catalog)
    monkeypatch.setattr(module, "catalog", catalog)
    monkeypatch.setattr(module, "source_service", service)
    monkeypatch.setattr(module.settings, "chat_db_path", tmp_path / "chats.db")

    async with module.app.router.lifespan_context(module.app):
        async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as client:
            bad = await client.post("/sources/csv", files={"file": ("bad.csv", b"id;value\n1;2;3\n", "text/csv")})
            assert bad.status_code == 400
            assert bad.json()["detail"]["report"]["rejected_rows"] == 1
            assert bad.json()["detail"]["report"]["rows_read"] == 1

            first_bytes = "Код;Сумма\n001;10,50\n".encode("utf-16")
            first = await client.post("/sources/csv", files={"file": ("sales.csv", first_bytes, "text/csv")})
            assert first.status_code == 200
            first_data = first.json()
            assert first_data["import_report"]["encoding"] == "utf-16"
            source_id, snapshot_id = first_data["source_id"], first_data["snapshot_id"]

            second = await client.post("/sources/csv", data={"source_id": source_id}, files={
                "file": ("sales.csv", b"id;amount\n001;20\n", "text/csv")
            })
            assert second.status_code == 200
            assert second.json()["snapshot_id"] != snapshot_id
            versions = (await client.get(f"/sources/{source_id}/versions")).json()
            assert [version["snapshot_id"] for version in versions] == [snapshot_id, second.json()["snapshot_id"]]
            original = await client.get(f"/sources/{source_id}/versions/{snapshot_id}/download")
            assert original.status_code == 200
            assert original.content == first_bytes
