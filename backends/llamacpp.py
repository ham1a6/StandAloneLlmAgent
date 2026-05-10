from agent.models import Message, ToolSchema, ChatResponse
from backends.base import LLMBackend


class LlamaCppBackend(LLMBackend):
    """Phase 2 で実装予定。llama-cpp-python を使ったローカル GGUF モデルの実行。"""

    def __init__(self, **kwargs):
        raise NotImplementedError(
            "LlamaCpp バックエンドは Phase 2 で実装予定です。\n"
            "現在は settings.yaml の backend: ollama を使用してください。"
        )

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
    ) -> ChatResponse:
        raise NotImplementedError

    def is_available(self) -> bool:
        return False
