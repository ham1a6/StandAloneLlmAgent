from agent.models import Message


class ContextManager:
    def __init__(self, max_messages: int = 40):
        self._system: Message | None = None
        self._messages: list[Message] = []
        self.max_messages = max_messages

    def set_system(self, content: str) -> None:
        self._system = Message(role="system", content=content)

    def add(self, message: Message) -> None:
        self._messages.append(message)
        self._trim()

    def _trim(self) -> None:
        if len(self._messages) > self.max_messages:
            self._messages = self._messages[-self.max_messages:]

    def get_messages(self) -> list[Message]:
        if self._system:
            return [self._system] + self._messages
        return list(self._messages)

    def clear(self) -> None:
        self._messages = []
