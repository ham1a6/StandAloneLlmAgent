from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    def run(self, user_prompt: str, on_text_chunk: Callable[[str], None] | None = None) -> str:
        self.context.add(Message(role="user", content=user_prompt))
        tools = self.dispatcher.get_schemas()

        for _ in range(self.max_steps):
            response = self.backend.chat_stream(
                messages=self.context.get_messages(),
                tools=tools,
                on_chunk=on_text_chunk,
            )

            if response.message.tool_calls:
                self.context.add(response.message)

                # task_done is always handled synchronously and terminates the loop
                for tc in response.message.tool_calls:
                    if tc.name == _TASK_DONE:
                        result = tc.arguments.get("result", "完了しました")
                        if self.on_tool_call:
                            self.on_tool_call(tc.name, tc.arguments)
                        if self.on_tool_result:
                            self.on_tool_result(tc.name, result)
                        return result

                # Notify all tool calls before execution
                for tc in response.message.tool_calls:
                    if self.on_tool_call:
                        self.on_tool_call(tc.name, tc.arguments)

                # Execute tool calls — parallel when multiple, direct when single
                results: dict[str, str] = {}
                if len(response.message.tool_calls) == 1:
                    tc = response.message.tool_calls[0]
                    results[tc.id] = self.dispatcher.dispatch(tc)
                    if self.on_tool_result:
                        self.on_tool_result(tc.name, results[tc.id])
                else:
                    with ThreadPoolExecutor() as executor:
                        future_to_tc = {
                            executor.submit(self.dispatcher.dispatch, tc): tc
                            for tc in response.message.tool_calls
                        }
                        for future in as_completed(future_to_tc):
                            tc = future_to_tc[future]
                            results[tc.id] = future.result()
                            if self.on_tool_result:
                                self.on_tool_result(tc.name, results[tc.id])

                # Add results to context in original order
                for tc in response.message.tool_calls:
                    self.context.add(
                        Message(role="tool", content=results[tc.id], tool_call_id=tc.id)
                    )
            else:
                content = response.message.content or ""
                self.context.add(response.message)
                return content

        return f"Error: max_steps ({self.max_steps}) を超過しました。タスクが複雑すぎる可能性があります。"

    def reset(self) -> None:
        self.context.clear()
        self.context.set_system(build_system_prompt())
