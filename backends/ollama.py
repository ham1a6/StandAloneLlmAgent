from __future__ import annotations
import json
from typing import Any, Callable
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

        # Fallback: some Ollama versions return tool calls as JSON text in content
        # instead of the structured tool_calls field. Parse them here.
        if not tool_calls and content:
            tool_calls = self._extract_text_tool_calls(content)
            if tool_calls:
                content = None

        message = Message(
            role=msg_data.get("role", "assistant"),
            content=content,
            tool_calls=tool_calls,
        )
        return ChatResponse(message=message, done=data.get("done", True))

    def _extract_text_tool_calls(self, text: str) -> list[ToolCall] | None:
        """Parse tool calls embedded as JSON in content (Ollama <=0.3 / some model variants)."""
        results: list[ToolCall] = []
        # Strip markdown fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.splitlines()[1:])
            cleaned = cleaned.rsplit("```", 1)[0].strip()

        # Split on lines — each line may be a separate JSON tool call
        for i, line in enumerate(cleaned.splitlines()):
            line = line.strip()
            if not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = obj.get("name")
            # Accept both {"arguments": ...} and {"parameters": ...}
            args = obj.get("arguments") or obj.get("parameters") or {}
            if not name or not isinstance(args, dict):
                continue
            results.append(ToolCall(id=f"call_{i}", name=name, arguments=args))

        # Also try the entire cleaned block as one JSON object
        if not results and cleaned.startswith("{") and cleaned.endswith("}"):
            try:
                obj = json.loads(cleaned)
                name = obj.get("name")
                args = obj.get("arguments") or obj.get("parameters") or {}
                if name and isinstance(args, dict):
                    results.append(ToolCall(id="call_0", name=name, arguments=args))
            except json.JSONDecodeError:
                pass

        return results or None

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> ChatResponse:
        # When tools are provided, use non-streaming to avoid showing raw tool-call JSON
        # as text — some Ollama versions embed tool calls in content rather than tool_calls.
        if tools:
            response = self.chat(messages, tools)
            if on_chunk and response.message.content:
                on_chunk(response.message.content)
            return response

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._to_dict(m) for m in messages],
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_window,
            },
        }

        accumulated: list[str] = []
        final_data: dict[str, Any] = {}
        with httpx.Client(timeout=300) as client:
            with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        accumulated.append(chunk)
                        if on_chunk:
                            on_chunk(chunk)
                    if data.get("done"):
                        final_data = data
                        break

        result = self._parse_response(final_data)
        if not result.message.tool_calls and accumulated and not result.message.content:
            result.message.content = "".join(accumulated)
        return result

    def is_available(self) -> bool:
        try:
            with httpx.Client(timeout=5) as client:
                r = client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False
