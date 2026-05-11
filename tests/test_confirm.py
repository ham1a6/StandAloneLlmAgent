"""Tests for on_confirm (tool execution confirmation) in Agent."""
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
    def __init__(self, result: str = "ok"):
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


# ---------------------------------------------------------------------------
# on_confirm=None (default) — all tools run without asking
# ---------------------------------------------------------------------------

def test_no_confirm_runs_tool():
    dispatcher = _MockDispatcher()
    agent = Agent(
        backend=_MockBackend([_tool(("bash", {"command": "ls"})), _text("done")]),
        dispatcher=dispatcher,
    )
    agent.run("test")
    assert len(dispatcher.calls) == 1


# ---------------------------------------------------------------------------
# on_confirm returns True — tool runs
# ---------------------------------------------------------------------------

def test_confirm_approved_runs_tool():
    dispatcher = _MockDispatcher()
    agent = Agent(
        backend=_MockBackend([_tool(("bash", {"command": "ls"})), _text("done")]),
        dispatcher=dispatcher,
        on_confirm=lambda name, args: True,
    )
    agent.run("test")
    assert len(dispatcher.calls) == 1


def test_confirm_approved_result_passed_to_context(clean_registry):
    dispatcher = _MockDispatcher(result="hello.txt")
    captured_results: list[str] = []
    agent = Agent(
        backend=_MockBackend([_tool(("read_file", {"path": "x.py"})), _text("done")]),
        dispatcher=dispatcher,
        on_confirm=lambda name, args: True,
        on_tool_result=lambda name, res: captured_results.append(res),
    )
    agent.run("test")
    assert captured_results == ["hello.txt"]


# ---------------------------------------------------------------------------
# on_confirm returns False — tool is cancelled
# ---------------------------------------------------------------------------

def test_confirm_denied_does_not_dispatch():
    dispatcher = _MockDispatcher()
    agent = Agent(
        backend=_MockBackend([_tool(("bash", {"command": "rm -rf /"})), _text("stopped")]),
        dispatcher=dispatcher,
        on_confirm=lambda name, args: False,
    )
    agent.run("test")
    assert len(dispatcher.calls) == 0


def test_confirm_denied_returns_cancelled_message():
    results: list[str] = []
    agent = Agent(
        backend=_MockBackend([_tool(("bash", {"command": "ls"})), _text("ok")]),
        dispatcher=_MockDispatcher(),
        on_confirm=lambda name, args: False,
        on_tool_result=lambda name, res: results.append(res),
    )
    agent.run("test")
    assert any("Cancelled" in r for r in results)


def test_confirm_denied_agent_continues():
    """After a cancellation the agent should keep running and eventually terminate."""
    dispatcher = _MockDispatcher()
    agent = Agent(
        backend=_MockBackend([
            _tool(("bash", {"command": "ls"})),
            _text("ok, I give up"),
        ]),
        dispatcher=dispatcher,
        on_confirm=lambda name, args: False,
    )
    result = agent.run("test")
    assert result == "ok, I give up"
    assert len(dispatcher.calls) == 0


# ---------------------------------------------------------------------------
# Selective confirmation — only confirm specific tools
# ---------------------------------------------------------------------------

def test_confirm_only_bash_not_read_file():
    dispatcher = _MockDispatcher()
    confirmed_tools: list[str] = []

    def selective_confirm(name: str, args: dict) -> bool:
        if name == "bash":
            confirmed_tools.append(name)
            return False  # deny bash
        return True  # allow everything else

    agent = Agent(
        backend=_MockBackend([
            _tool(("read_file", {"path": "f.py"})),
            _tool(("bash", {"command": "python f.py"})),
            _text("done"),
        ]),
        dispatcher=dispatcher,
        on_confirm=selective_confirm,
    )
    agent.run("test")
    assert confirmed_tools == ["bash"]
    # read_file ran, bash did not
    ran = [tc.name for tc in dispatcher.calls]
    assert "read_file" in ran
    assert "bash" not in ran


# ---------------------------------------------------------------------------
# task_done is never passed to on_confirm
# ---------------------------------------------------------------------------

def test_task_done_not_passed_to_confirm():
    confirmed: list[str] = []
    agent = Agent(
        backend=_MockBackend([_tool(("task_done", {"result": "finished"}))]),
        dispatcher=_MockDispatcher(),
        on_confirm=lambda name, args: confirmed.append(name) or True,
    )
    agent.run("test")
    assert "task_done" not in confirmed


# ---------------------------------------------------------------------------
# Multiple tool calls in one response — each confirmed individually
# ---------------------------------------------------------------------------

def test_multiple_tools_each_confirmed():
    dispatcher = _MockDispatcher()
    confirmed: list[str] = []

    def confirm(name: str, args: dict) -> bool:
        confirmed.append(name)
        return name != "bash"  # deny bash, allow others

    agent = Agent(
        backend=_MockBackend([
            _tool(("read_file", {"path": "a.py"}), ("bash", {"command": "ls"})),
            _text("done"),
        ]),
        dispatcher=dispatcher,
        on_confirm=confirm,
    )
    agent.run("test")
    assert set(confirmed) == {"read_file", "bash"}
    ran = {tc.name for tc in dispatcher.calls}
    assert "read_file" in ran
    assert "bash" not in ran
