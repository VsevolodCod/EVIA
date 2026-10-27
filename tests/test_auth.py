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
            from app.ownership import current_owner
            token = current_owner.set(created.json()["id"])
            try:
                chart = module.tool_registry.execute("build_chart", {"definition": {
                    "type": "kpi", "title": "Private KPI",
                    "field": {"source_id": source_id, "field": "b"}, "aggregate": "sum",
                }, "filters": []})
                assert chart.ok and chart.data["success"]
                chart_id = chart.data["chart_id"]
                dashboard = module.tool_registry.execute("compose_dashboard", {
                    "title": "Private dashboard", "chart_ids": [chart_id],
                })
                assert dashboard.ok and dashboard.data["success"]
                dashboard_id = dashboard.data["dashboard"]["id"]
            finally:
                current_owner.reset(token)
            assert (await first.get(f"/charts/{chart_id}")).status_code == 200
            assert (await second.get(f"/charts/{chart_id}")).status_code == 404
            assert (await second.get(f"/dashboards/{dashboard_id}")).status_code == 404
            assert dashboard_id not in (await second.get("/dashboards/ids")).json()["dashboard_ids"]
            chat_id = (await first.post("/chats", json={"title": "Private"})).json()["chat_id"]
            assert (await second.get(f"/chats/{chat_id}")).status_code == 404
            assert (await second.delete(f"/chats/{chat_id}")).status_code == 404
            assert (await second.get("/chats")).json() == []
            assert (await first.patch("/auth/profile", json={"name": "Новое имя"})).json()["name"] == "Новое имя"
            assert (await first.post("/auth/logout")).status_code == 204
            assert (await first.get("/sources")).status_code == 401


@pytest.mark.asyncio
async def test_recovery_request_is_generic_for_unknown_email(auth_module, monkeypatch):
    module = auth_module
    sent = []
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("MAIL_FROM", "EVIA <hello@example.com>")
    monkeypatch.setattr("app.auth_routes.send_reset_code", lambda address, code: sent.append((address, code)))
    async with module.app.router.lifespan_context(module.app), AsyncClient(
        transport=ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        assert (await client.post("/auth/register", json={
            "email": "known@example.com", "password": "known strong password", "name": "Known",
        })).status_code == 201
        known = await client.post("/auth/reset/request", json={"email": "known@example.com"})
        unknown = await client.post("/auth/reset/request", json={"email": "missing@example.com"})
        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json() == {"ok": True}
        assert len(sent) == 1 and sent[0][0] == "known@example.com"


@pytest.mark.asyncio
async def test_legacy_data_is_claimed_by_explicit_bootstrap_account(auth_module, monkeypatch):
    from app.chat_manager import ChatManager
    from app.db.chat.engine import create_chat_database, initialize_chat_database
    from app.models import Chat, DataSource

    module = auth_module
    module.catalog.upsert_source(DataSource(source_id="old-source", name="Old", source_type="csv"))
    old_engine, old_sessions = create_chat_database(module.settings.chat_db_path)
    await initialize_chat_database(old_engine)
    await ChatManager(old_sessions).create_persistent_chat(Chat(chat_id="old-chat", title="Old chat", temporary=False))
    await old_engine.dispose()
    monkeypatch.setattr(module.settings, "auth_bootstrap_email", "owner@example.com")
    monkeypatch.setattr(module.settings, "auth_bootstrap_password", "temporary bootstrap password")
    async with module.app.router.lifespan_context(module.app):
        async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as owner, AsyncClient(
            transport=ASGITransport(app=module.app), base_url="http://test"
        ) as stranger:
            assert (await owner.post("/auth/login", json={
                "email": "owner@example.com", "password": "temporary bootstrap password",
            })).status_code == 200
            assert [source["source_id"] for source in (await owner.get("/sources")).json()] == ["old-source"]
            assert [chat["chat_id"] for chat in (await owner.get("/chats")).json()] == ["old-chat"]
            await stranger.post("/auth/register", json={
                "email": "other@example.com", "password": "another strong password", "name": "Other",
            })
            assert (await stranger.get("/sources")).json() == []
            assert (await stranger.get("/chats")).json() == []


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
