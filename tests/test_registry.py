import pytest
from agent.models import ToolCall
from tools.registry import tool, ToolDispatcher, _registry


def test_tool_registered(clean_registry):
    @tool(name="_t_echo", description="echo")
    def _t_echo(msg: str) -> str:
        return msg

    assert "_t_echo" in _registry


def test_schema_required_params(clean_registry):
    @tool(name="_t_add", description="add")
    def _t_add(a: int, b: int) -> int:
        return a + b

    params = _registry["_t_add"].schema.function.parameters
    assert params["required"] == ["a", "b"]
    assert params["properties"]["a"]["type"] == "integer"
    assert params["properties"]["b"]["type"] == "integer"


def test_schema_optional_params(clean_registry):
    @tool(name="_t_opt", description="opt")
    def _t_opt(path: str, limit: int = 100) -> str:
        return path

    params = _registry["_t_opt"].schema.function.parameters
    assert params["required"] == ["path"]
    assert "limit" in params["properties"]
    assert "limit" not in params["required"]


def test_schema_string_type(clean_registry):
    @tool(name="_t_str", description="str")
    def _t_str(x: str) -> str:
        return x

    params = _registry["_t_str"].schema.function.parameters
    assert params["properties"]["x"]["type"] == "string"


def test_schema_bool_type(clean_registry):
    @tool(name="_t_bool", description="bool")
    def _t_bool(flag: bool) -> str:
        return str(flag)

    params = _registry["_t_bool"].schema.function.parameters
    assert params["properties"]["flag"]["type"] == "boolean"


def test_dispatcher_dispatch_success(clean_registry):
    @tool(name="_t_upper", description="upper")
    def _t_upper(text: str) -> str:
        return text.upper()

    dispatcher = ToolDispatcher()
    result = dispatcher.dispatch(ToolCall(name="_t_upper", arguments={"text": "hello"}))
    assert result == "HELLO"


def test_dispatcher_unknown_tool(clean_registry):
    dispatcher = ToolDispatcher(tool_names=[])
    result = dispatcher.dispatch(ToolCall(name="nonexistent", arguments={}))
    assert "unknown tool" in result


def test_dispatcher_exception_returns_error(clean_registry):
    @tool(name="_t_raise", description="raises")
    def _t_raise(x: str) -> str:
        raise ValueError("boom")

    dispatcher = ToolDispatcher()
    result = dispatcher.dispatch(ToolCall(name="_t_raise", arguments={"x": "y"}))
    assert "Error" in result
    assert "boom" in result


def test_dispatcher_invalid_args_returns_error(clean_registry):
    @tool(name="_t_typed", description="typed")
    def _t_typed(x: str) -> str:
        return x

    dispatcher = ToolDispatcher()
    result = dispatcher.dispatch(ToolCall(name="_t_typed", arguments={"wrong_key": "v"}))
    assert "Error" in result


def test_dispatcher_get_schemas(clean_registry):
    @tool(name="_t_s1", description="s1")
    def _t_s1(x: str) -> str:
        return x

    dispatcher = ToolDispatcher(tool_names=["_t_s1"])
    schemas = dispatcher.get_schemas()
    assert len(schemas) == 1
    assert schemas[0].function.name == "_t_s1"


def test_dispatcher_filters_tool_names(clean_registry):
    @tool(name="_t_a", description="a")
    def _t_a(x: str) -> str:
        return x

    @tool(name="_t_b", description="b")
    def _t_b(x: str) -> str:
        return x

    dispatcher = ToolDispatcher(tool_names=["_t_a"])
    names = [s.function.name for s in dispatcher.get_schemas()]
    assert "_t_a" in names
    assert "_t_b" not in names
