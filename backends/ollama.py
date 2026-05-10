from __future__ import annotations
import json
from typing import Any
import httpx
from agent.models import Message, ToolSchema, ChatResponse, ToolCall
from backends.base import LLMBackend


class OllamaBackend(LLMBackend):
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5-coder:7b",
        temperature: float = 0.2,
        context_window: int = 32768,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.context_window = context_window

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._to_dict(m) for m in messages],
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_window,
            },
        }
        if tools:
            payload["tools"] = [t.model_dump() for t in tools]

        with httpx.Client(timeout=300) as client:
            response = client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        return self._parse_response(data)

    def _to_dict(self, msg: Message) -> dict[str, Any]:
        d: dict[str, Any] = {"role": msg.role}
        if msg.content is not None:
            d["content"] = msg.content
        elif msg.role == "tool":
            d["content"] = ""
        if msg.tool_calls:
            d["tool_calls"] = [
                {"function": {"name": tc.name, "arguments": tc.arguments}}
                for tc in msg.tool_calls
            ]
        return d

    def _parse_response(self, data: dict[str, Any]) -> ChatResponse:
        msg_data = data.get("message", {})
        content = msg_data.get("content") or None

        tool_calls: list[ToolCall] | None = None
        raw_tcs = msg_data.get("tool_calls")
        if raw_tcs:
            tool_calls = []
            for i, tc in enumerate(raw_tcs):
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", f"call_{i}"),
                        name=fn.get("name", ""),
                        arguments=args,
                    )
                )

        message = Message(
            role=msg_data.get("role", "assistant"),
            content=content,
            tool_calls=tool_calls,
        )
        return ChatResponse(message=message, done=data.get("done", True))

    def is_available(self) -> bool:
        try:
            with httpx.Client(timeout=5) as client:
                r = client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False
