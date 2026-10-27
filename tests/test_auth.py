"""Account behavior and tenant boundaries; uses an ephemeral auth database."""

import importlib

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def auth_module(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-only-for-ci")
    monkeypatch.setenv("BI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("CHAT_DB_PATH", str(tmp_path / "chats.db"))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    module = importlib.reload(importlib.import_module("app.main"))
    yield module
    monkeypatch.undo()
    importlib.reload(module)


@pytest.mark.asyncio
async def test_auth_session_profile_and_source_isolation(auth_module):
    module = auth_module
    async with module.app.router.lifespan_context(module.app):
        async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as first, AsyncClient(
            transport=ASGITransport(app=module.app), base_url="http://test"
        ) as second:
            assert (await first.get("/sources")).status_code == 401
            assert (await first.get("/auth/me")).status_code == 401
            created = await first.post("/auth/register", json={
                "email": "First@Example.com", "password": "correct horse battery", "name": "Первый",
            })
            assert created.status_code == 201
            assert created.json()["email"] == "first@example.com"
            assert "httponly" in created.headers["set-cookie"].lower()
            assert (await first.get("/auth/me")).json()["name"] == "Первый"
            assert (await second.post("/auth/register", json={
                "email": "second@example.com", "password": "another strong password", "name": "Второй",
            })).status_code == 201
            upload = await first.post("/sources/csv", files={"file": ("sales.csv", b"a,b\n1,2\n", "text/csv")})
            assert upload.status_code == 200
            source_id = upload.json()["source_id"]
            assert [row["source_id"] for row in (await first.get("/sources")).json()] == [source_id]
            assert (await second.get("/sources")).json() == []
            assert (await second.get(f"/sources/{source_id}/preview")).status_code == 404
            assert (await second.post("/agent/ask", json={"question": "show", "source_ids": [source_id]})).status_code == 404
            chat_id = (await first.post("/chats", json={"title": "Private"})).json()["chat_id"]
            assert (await second.get(f"/chats/{chat_id}")).status_code == 404
            assert (await second.delete(f"/chats/{chat_id}")).status_code == 404
            assert (await second.get("/chats")).json() == []
            assert (await first.patch("/auth/profile", json={"name": "Новое имя"})).json()["name"] == "Новое имя"
            assert (await first.post("/auth/logout")).status_code == 204
            assert (await first.get("/sources")).status_code == 401


@pytest.mark.asyncio
async def test_reset_code_is_single_use_and_revokes_sessions(tmp_path):
    from app.auth import AuthStore

    store = AuthStore(f"sqlite:///{tmp_path / 'auth.db'}", secret="test-secret-only-for-ci")
    store.initialize()
    account = store.register("user@example.com", "correct horse battery", "User")
    token = store.create_session(account.id)
    code = store.issue_reset_code("user@example.com")
    assert code is not None
    assert store.reset_password("user@example.com", code, "new correct horse battery")
    assert store.get_session_user(token) is None
    assert not store.reset_password("user@example.com", code, "another new password")
    assert store.authenticate("user@example.com", "new correct horse battery") is not None
    assert store.authenticate("user@example.com", "correct horse battery") is None
    store.close()
