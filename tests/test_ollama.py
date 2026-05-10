import json
import pytest
from unittest.mock import patch, MagicMock
from agent.models import Message, ToolCall
from backends.ollama import OllamaBackend


def _mock_client(response_data: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    mock_resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.post.return_value = mock_resp
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


def _patch(response_data: dict):
    return patch("backends.ollama.httpx.Client", return_value=_mock_client(response_data))


def test_chat_text_response():
    backend = OllamaBackend()
    with _patch({"message": {"role": "assistant", "content": "Hello!"}, "done": True}):
        r = backend.chat([Message(role="user", content="Hi")])
    assert r.message.content == "Hello!"
    assert r.message.tool_calls is None
    assert r.done is True


def test_chat_tool_call_response():
    backend = OllamaBackend()
    data = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": {"path": "foo.py"}}}
            ],
        },
        "done": True,
    }
    with _patch(data):
        r = backend.chat([Message(role="user", content="read")])
    assert r.message.tool_calls is not None
    tc = r.message.tool_calls[0]
    assert tc.name == "read_file"
    assert tc.arguments == {"path": "foo.py"}


def test_chat_tool_call_args_as_json_string():
    """Ollama が arguments を JSON 文字列で返すケースに対応できること。"""
    backend = OllamaBackend()
    data = {
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"function": {"name": "bash", "arguments": json.dumps({"command": "ls"})}}
            ],
        },
        "done": True,
    }
    with _patch(data):
        r = backend.chat([Message(role="user", content="run")])
    tc = r.message.tool_calls[0]
    assert isinstance(tc.arguments, dict)
    assert tc.arguments["command"] == "ls"


def test_to_dict_user_message():
    backend = OllamaBackend()
    d = backend._to_dict(Message(role="user", content="hello"))
    assert d == {"role": "user", "content": "hello"}


def test_to_dict_tool_message():
    backend = OllamaBackend()
    d = backend._to_dict(Message(role="tool", content="result", tool_call_id="call_abc"))
    assert d["role"] == "tool"
    assert d["content"] == "result"


def test_to_dict_assistant_with_tool_calls():
    backend = OllamaBackend()
    tc = ToolCall(name="bash", arguments={"command": "ls"})
    d = backend._to_dict(Message(role="assistant", tool_calls=[tc]))
    assert "tool_calls" in d
    assert d["tool_calls"][0]["function"]["name"] == "bash"
    assert d["tool_calls"][0]["function"]["arguments"] == {"command": "ls"}


def test_to_dict_tool_message_no_content_defaults_empty():
    backend = OllamaBackend()
    d = backend._to_dict(Message(role="tool", content=None))
    assert d["content"] == ""


def test_is_available_true():
    backend = OllamaBackend()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    client = MagicMock()
    client.get.return_value = mock_resp
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    with patch("backends.ollama.httpx.Client", return_value=client):
        assert backend.is_available() is True


def test_is_available_false_on_exception():
    backend = OllamaBackend()
    with patch("backends.ollama.httpx.Client", side_effect=Exception("connection refused")):
        assert backend.is_available() is False
