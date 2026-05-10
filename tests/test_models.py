from agent.models import ToolCall, ToolSchema, ToolFunction, Message, ChatResponse


def test_toolcall_auto_id():
    tc = ToolCall(name="foo", arguments={})
    assert tc.id.startswith("call_")


def test_toolcall_distinct_ids():
    tc1 = ToolCall(name="foo", arguments={})
    tc2 = ToolCall(name="foo", arguments={})
    assert tc1.id != tc2.id


def test_message_defaults():
    m = Message(role="user", content="hello")
    assert m.tool_calls is None
    assert m.tool_call_id is None


def test_message_with_tool_calls():
    tc = ToolCall(name="read_file", arguments={"path": "foo.py"})
    m = Message(role="assistant", tool_calls=[tc])
    assert len(m.tool_calls) == 1
    assert m.tool_calls[0].name == "read_file"


def test_chatresponse_done_defaults_to_true():
    m = Message(role="assistant", content="hi")
    r = ChatResponse(message=m)
    assert r.done is True


def test_toolschema_type_is_function():
    schema = ToolSchema(
        function=ToolFunction(
            name="my_tool",
            description="does something",
            parameters={"type": "object", "properties": {}, "required": []},
        )
    )
    assert schema.type == "function"
    assert schema.function.name == "my_tool"
