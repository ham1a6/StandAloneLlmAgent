import pytest
from agent.models import ChatResponse, Message, ToolCall
from agent.core import Agent
from backends.base import LLMBackend


class _MockBackend(LLMBackend):
    def __init__(self, responses):
        self._iter = iter(responses)

    def chat(self, messages, tools=None):
        return next(self._iter)

    def is_available(self):
        return True


class _MockDispatcher:
    def __init__(self, result: str = "tool result"):
        self.calls: list[ToolCall] = []
        self._result = result

    def get_schemas(self):
        return []

    def dispatch(self, tool_call: ToolCall) -> str:
        self.calls.append(tool_call)
        return self._result


def _text(content: str) -> ChatResponse:
    return ChatResponse(message=Message(role="assistant", content=content))


def _tool(*calls) -> ChatResponse:
    tcs = [ToolCall(name=n, arguments=a) for n, a in calls]
    return ChatResponse(message=Message(role="assistant", tool_calls=tcs))


def test_run_returns_text_response():
    agent = Agent(backend=_MockBackend([_text("Hello!")]), dispatcher=_MockDispatcher())
    assert agent.run("hi") == "Hello!"


def test_run_task_done_stops_loop():
    agent = Agent(
        backend=_MockBackend([_tool(("task_done", {"result": "all done"}))]),
        dispatcher=_MockDispatcher(),
    )
    assert agent.run("do it") == "all done"


def test_run_task_done_not_dispatched():
    dispatcher = _MockDispatcher()
    agent = Agent(
        backend=_MockBackend([_tool(("task_done", {"result": "done"}))]),
        dispatcher=dispatcher,
    )
    agent.run("go")
    assert len(dispatcher.calls) == 0


def test_run_tool_then_text():
    dispatcher = _MockDispatcher(result="file contents")
    agent = Agent(
        backend=_MockBackend([
            _tool(("read_file", {"path": "foo.py"})),
            _text("The file has 2 lines."),
        ]),
        dispatcher=dispatcher,
    )
    result = agent.run("read foo.py")
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0].name == "read_file"
    assert result == "The file has 2 lines."


def test_run_max_steps_exceeded():
    responses = [_tool(("bash", {"command": "ls"})) for _ in range(50)]
    agent = Agent(
        backend=_MockBackend(responses),
        dispatcher=_MockDispatcher(),
        max_steps=3,
    )
    result = agent.run("loop")
    assert "max_steps" in result


def test_on_tool_call_callback_fired():
    calls = []
    agent = Agent(
        backend=_MockBackend([
            _tool(("bash", {"command": "echo hi"})),
            _text("done"),
        ]),
        dispatcher=_MockDispatcher(),
        on_tool_call=lambda name, args: calls.append((name, args)),
    )
    agent.run("test")
    assert calls == [("bash", {"command": "echo hi"})]


def test_on_tool_result_callback_fired():
    results = []
    agent = Agent(
        backend=_MockBackend([
            _tool(("bash", {"command": "ls"})),
            _text("done"),
        ]),
        dispatcher=_MockDispatcher(result="file.txt"),
        on_tool_result=lambda name, res: results.append((name, res)),
    )
    agent.run("test")
    assert results == [("bash", "file.txt")]


def test_task_done_fires_result_callback():
    results = []
    agent = Agent(
        backend=_MockBackend([_tool(("task_done", {"result": "finished"}))]),
        dispatcher=_MockDispatcher(),
        on_tool_result=lambda name, res: results.append((name, res)),
    )
    agent.run("test")
    assert results == [("task_done", "finished")]


def test_reset_clears_conversation():
    backend = _MockBackend([_text("first"), _text("second")])
    dispatcher = _MockDispatcher()
    agent = Agent(backend=backend, dispatcher=dispatcher)
    agent.run("first message")
    agent.reset()
    msgs = agent.context.get_messages()
    assert len(msgs) == 1
    assert msgs[0].role == "system"


def test_empty_response_nudges_and_continues():
    """空レスポンスが返ったとき、モデルへの再試行メッセージを注入してループを継続する。"""
    dispatcher = _MockDispatcher()
    agent = Agent(
        backend=_MockBackend([
            _text(""),          # 空レスポンス → ナッジして再試行
            _text("all done"),  # 次のターンで正常応答
        ]),
        dispatcher=dispatcher,
    )
    result = agent.run("test")
    assert result == "all done"
    # ナッジメッセージが context に入っていること
    msgs = agent.context.get_messages()
    nudge_msgs = [m for m in msgs if m.role == "user" and "empty" in (m.content or "")]
    assert len(nudge_msgs) == 1


def test_consecutive_empty_responses_returns_error():
    """空レスポンスが2回続いたらエラーメッセージを返してループを抜ける。"""
    agent = Agent(
        backend=_MockBackend([_text(""), _text(""), _text("never reached")]),
        dispatcher=_MockDispatcher(),
    )
    result = agent.run("test")
    assert "Error" in result
    assert "リセット" in result


def test_user_message_added_to_context():
    backend = _MockBackend([_text("ok")])
    agent = Agent(backend=backend, dispatcher=_MockDispatcher())
    agent.run("hello there")
    msgs = agent.context.get_messages()
    user_msgs = [m for m in msgs if m.role == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0].content == "hello there"
