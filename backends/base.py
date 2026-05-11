from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable
from agent.models import Message, ToolSchema, ChatResponse


class LLMBackend(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
    ) -> ChatResponse: ...

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> ChatResponse:
        response = self.chat(messages, tools)
        if on_chunk and response.message.content:
            on_chunk(response.message.content)
        return response

    @abstractmethod
    def is_available(self) -> bool: ...
