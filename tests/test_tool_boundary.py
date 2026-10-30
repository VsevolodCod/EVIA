"""Model-supplied tool calls cannot turn private exception text into output."""

from app.tools.base import ToolDefinition, ToolRegistry


def test_tool_execution_error_does_not_return_secret_canary():
    registry = ToolRegistry()

    def leak(**_):
        raise RuntimeError("postgresql://reader:SECRET_CANARY@internal-db/private")

    registry.register(ToolDefinition(
        name="probe", description="test", parameters={"source_id": {"type": "string"}},
        required=["source_id"], handler=leak,
    ))
    result = registry.execute("probe", {"source_id": "selected"})
    assert not result.ok
    assert result.error == "TOOL_EXECUTION_FAILED"
    assert "SECRET_CANARY" not in result.model_dump_json()


def test_tool_arguments_are_checked_recursively_before_handler():
    registry = ToolRegistry()
    called = False

    def handler(**_):
        nonlocal called
        called = True
        return {"ok": True}

    registry.register(ToolDefinition(
        name="build", description="test",
        parameters={"definition": {"type": "object", "properties": {
            "source_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        }, "required": ["source_id", "limit"], "additionalProperties": False}},
        required=["definition"], handler=handler,
    ))
    for payload in (
        {"definition": {"source_id": "s", "limit": "10"}},
        {"definition": {"source_id": "s", "limit": 101}},
        {"definition": {"source_id": "s", "limit": 1, "extra": "SECRET_CANARY"}},
        {"definition": {"source_id": "s", "limit": 1}, "SECRET_CANARY": 1},
    ):
        result = registry.execute("build", payload)
        assert result.error == "INVALID_TOOL_ARGUMENTS"
        assert "SECRET_CANARY" not in result.model_dump_json()
    assert not called
    assert registry.execute("build", {"definition": {"source_id": "s", "limit": 1}}).ok
