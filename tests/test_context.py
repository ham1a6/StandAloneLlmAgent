from agent.models import Message
from agent.context import ContextManager


def test_empty_context_no_system():
    ctx = ContextManager()
    assert ctx.get_messages() == []


def test_system_message_prepended():
    ctx = ContextManager()
    ctx.set_system("You are an assistant.")
    msgs = ctx.get_messages()
    assert len(msgs) == 1
    assert msgs[0].role == "system"
    assert msgs[0].content == "You are an assistant."


def test_add_and_retrieve():
    ctx = ContextManager()
    ctx.set_system("sys")
    ctx.add(Message(role="user", content="hello"))
    ctx.add(Message(role="assistant", content="hi"))
    msgs = ctx.get_messages()
    assert len(msgs) == 3
    assert msgs[1].role == "user"
    assert msgs[2].role == "assistant"


def test_trim_keeps_latest():
    ctx = ContextManager(max_messages=3)
    for i in range(5):
        ctx.add(Message(role="user", content=str(i)))
    msgs = ctx.get_messages()
    assert len(msgs) == 3
    assert msgs[0].content == "2"
    assert msgs[2].content == "4"


def test_clear_removes_messages_keeps_system():
    ctx = ContextManager()
    ctx.set_system("sys")
    ctx.add(Message(role="user", content="hello"))
    ctx.clear()
    msgs = ctx.get_messages()
    assert len(msgs) == 1
    assert msgs[0].role == "system"


def test_system_update():
    ctx = ContextManager()
    ctx.set_system("first")
    ctx.set_system("second")
    msgs = ctx.get_messages()
    assert msgs[0].content == "second"
