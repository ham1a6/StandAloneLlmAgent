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
        on_confirm: Callable[[str, dict], bool] | None = None,
    ):
        self.backend = backend
        self.dispatcher = dispatcher
        self.max_steps = max_steps
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.on_confirm = on_confirm
        self.context = ContextManager()
        self.context.set_system(build_system_prompt())

    def run(self, user_prompt: str, on_text_chunk: Callable[[str], None] | None = None) -> str:
        self.context.add(Message(role="user", content=user_prompt))
        tools = self.dispatcher.get_schemas()
        consecutive_empty = 0

        for _ in range(self.max_steps):
            response = self.backend.chat_stream(
                messages=self.context.get_messages(),
                tools=tools,
                on_chunk=on_text_chunk,
            )

            if response.message.tool_calls:
                consecutive_empty = 0
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

                # Notify and optionally confirm each tool call before execution
                confirmed: list = []
                for tc in response.message.tool_calls:
                    if self.on_tool_call:
                        self.on_tool_call(tc.name, tc.arguments)
                    if self.on_confirm and not self.on_confirm(tc.name, tc.arguments):
                        confirmed.append(None)  # None = cancelled
                    else:
                        confirmed.append(tc)

                # Execute approved tool calls; mark cancelled ones without dispatching
                results: dict[str, str] = {}
                approved = [tc for tc in confirmed if tc is not None]
                cancelled = [
                    response.message.tool_calls[i]
                    for i, tc in enumerate(confirmed)
                    if tc is None
                ]
                for tc in cancelled:
                    results[tc.id] = "Cancelled by user."
                    if self.on_tool_result:
                        self.on_tool_result(tc.name, results[tc.id])

                if len(approved) == 1:
                    tc = approved[0]
                    results[tc.id] = self.dispatcher.dispatch(tc)
                    if self.on_tool_result:
                        self.on_tool_result(tc.name, results[tc.id])
                elif approved:
                    with ThreadPoolExecutor() as executor:
                        future_to_tc = {
                            executor.submit(self.dispatcher.dispatch, tc): tc
                            for tc in approved
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
                if not content:
                    # Empty response — stripped template token or malformed output.
                    # Nudge the model to continue rather than silently stopping.
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        return "Error: モデルからの応答が連続して空でした。/reset で会話をリセットして再試行してください。"
                    self.context.add(Message(
                        role="user",
                        content="Your last response was empty. Please continue: call a tool or call task_done.",
                    ))
                    continue
                consecutive_empty = 0
                self.context.add(response.message)
                return content

        return f"Error: max_steps ({self.max_steps}) を超過しました。タスクが複雑すぎる可能性があります。"

    def reset(self) -> None:
        self.context.clear()
        self.context.set_system(build_system_prompt())
