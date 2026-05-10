from abc import ABC, abstractmethod
from agent.models import Message, ToolSchema, ChatResponse


class LLMBackend(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
    ) -> ChatResponse: ...

    @abstractmethod
    def is_available(self) -> bool: ...
