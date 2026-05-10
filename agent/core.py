from __future__ import annotations
from typing import Callable
from agent.models import Message
from agent.context import ContextManager
from agent.prompt import build_system_prompt
from backends.base import LLMBackend
from tools.registry import ToolDispatcher

_TASK_DONE = "task_done"


class Agent:
    def __init__(
        self,
        backend: LLMBackend,
        dispatcher: ToolDispatcher,
        max_steps: int = 30,
        on_tool_call: Callable[[str, dict], None] | None = None,
        on_tool_result: Callable[[str, str], None] | None = None,
    ):
        self.backend = backend
        self.dispatcher = dispatcher
        self.max_steps = max_steps
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.context = ContextManager()
        self.context.set_system(build_system_prompt())

    def run(self, user_prompt: str) -> str:
        self.context.add(Message(role="user", content=user_prompt))
        tools = self.dispatcher.get_schemas()

        for _ in range(self.max_steps):
            response = self.backend.chat(
                messages=self.context.get_messages(),
                tools=tools,
            )

            if response.message.tool_calls:
                self.context.add(response.message)

                for tc in response.message.tool_calls:
                    if self.on_tool_call:
                        self.on_tool_call(tc.name, tc.arguments)

                    if tc.name == _TASK_DONE:
                        result = tc.arguments.get("result", "完了しました")
                        if self.on_tool_result:
                            self.on_tool_result(tc.name, result)
                        return result

                    result = self.dispatcher.dispatch(tc)
                    if self.on_tool_result:
                        self.on_tool_result(tc.name, result)

                    self.context.add(
                        Message(role="tool", content=result, tool_call_id=tc.id)
                    )
            else:
                content = response.message.content or ""
                self.context.add(response.message)
                return content

        return f"Error: max_steps ({self.max_steps}) を超過しました。タスクが複雑すぎる可能性があります。"

    def reset(self) -> None:
        self.context.clear()
        self.context.set_system(build_system_prompt())
