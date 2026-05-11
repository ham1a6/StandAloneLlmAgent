from __future__ import annotations
import json
import re
from typing import Any, Callable
import httpx
from agent.models import Message, ToolSchema, ChatResponse, ToolCall
from backends.base import LLMBackend

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
# Qwen2.5 chat-template tokens that sometimes leak into content
_TEMPLATE_TOKEN_RE = re.compile(r"<\|im_(start|end)\|>(\w+\n)?", re.DOTALL)


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
        # Send tools so Ollama can use native calling when available.
        # We also parse <tool_call> blocks as a fallback.
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
        raw = msg_data.get("content") or ""
        # Strip leaked Qwen chat-template tokens (e.g. <|im_start|>user\n)
        content = _TEMPLATE_TOKEN_RE.sub("", raw).strip() or None

        tool_calls: list[ToolCall] | None = None

        # 1. Try native tool_calls field (works on newer Ollama versions)
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

        # 2. Fallback: parse <tool_call> blocks or JSON lines from content
        if not tool_calls and content:
            parsed, remaining = self._extract_tool_calls(content)
            if parsed:
                tool_calls = parsed
                content = remaining or None

        message = Message(
            role=msg_data.get("role", "assistant"),
            content=content,
            tool_calls=tool_calls,
        )
        return ChatResponse(message=message, done=data.get("done", True))

    def _extract_tool_calls(self, text: str) -> tuple[list[ToolCall] | None, str]:
        """Parse tool calls from text. Returns (tool_calls, text_with_tags_removed)."""
        results: list[ToolCall] = []

        # Primary: <tool_call>...</tool_call> blocks (Qwen2.5 native format)
        for i, m in enumerate(_TOOL_CALL_RE.finditer(text)):
            try:
                obj = json.loads(m.group(1))
                name = obj.get("name")
                args = obj.get("arguments") or obj.get("parameters") or {}
                if name and isinstance(args, dict):
                    results.append(ToolCall(id=f"call_{i}", name=name, arguments=args))
            except json.JSONDecodeError:
                pass

        if results:
            cleaned = _TOOL_CALL_RE.sub("", text).strip()
            return results, cleaned

        # Secondary: bare JSON lines {"name": ..., "arguments": ...}
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.splitlines()[1:])
            cleaned = cleaned.rsplit("```", 1)[0].strip()

        for i, line in enumerate(cleaned.splitlines()):
            line = line.strip()
            if not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                obj = json.loads(line)
                name = obj.get("name")
                args = obj.get("arguments") or obj.get("parameters") or {}
                if name and isinstance(args, dict):
                    results.append(ToolCall(id=f"call_{i}", name=name, arguments=args))
            except json.JSONDecodeError:
                pass

        if results:
            return results, ""

        # Tertiary: entire content is one JSON object
        if cleaned.startswith("{") and cleaned.endswith("}"):
            try:
                obj = json.loads(cleaned)
                name = obj.get("name")
                args = obj.get("arguments") or obj.get("parameters") or {}
                if name and isinstance(args, dict):
                    return [ToolCall(id="call_0", name=name, arguments=args)], ""
            except json.JSONDecodeError:
                pass

        return None, text

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> ChatResponse:
        # Buffer the full response first so we can strip <tool_call> blocks before display.
        # This avoids showing raw XML tags to the user when the model uses the text format.
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._to_dict(m) for m in messages],
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_window,
            },
        }
        if tools:
            payload["tools"] = [t.model_dump() for t in tools]

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
                    if data.get("done"):
                        final_data = data
                        break

        result = self._parse_response(final_data)

        # Merge streamed text with parsed result
        full_text = "".join(accumulated)
        if result.message.tool_calls:
            # Tool calls from native field — don't show raw content
            pass
        elif full_text:
            # Check full accumulated text for tool calls (streaming may miss them in done chunk)
            parsed, remaining = self._extract_tool_calls(full_text)
            if parsed:
                result.message.tool_calls = parsed
                result.message.content = remaining or None
            else:
                # Pure text response — stream it to the UI now
                result.message.content = full_text
                if on_chunk:
                    on_chunk(full_text)

        return result

    def is_available(self) -> bool:
        try:
            with httpx.Client(timeout=5) as client:
                r = client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False
