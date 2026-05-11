from __future__ import annotations
import sys
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML

import tools  # noqa: F401 — must be imported before ToolDispatcher() to register all tools
from config.settings import load_settings, Settings
from backends.ollama import OllamaBackend
from tools.registry import ToolDispatcher
from agent.core import Agent

console = Console()


def _build_session() -> PromptSession:
    kb = KeyBindings()

    @kb.add("s-enter")
    def _submit(event):
        event.current_buffer.validate_and_handle()

    return PromptSession(
        message=HTML("<ansigreen><b>&gt;</b></ansigreen> "),
        multiline=True,
        key_bindings=kb,
        prompt_continuation=lambda width, line_number, soft_wrap: "  ",
    )


def _make_agent(settings: Settings) -> Agent:
    if settings.backend == "ollama":
        backend = OllamaBackend(
            base_url=settings.ollama.base_url,
            model=settings.ollama.model,
            temperature=settings.ollama.temperature,
            context_window=settings.ollama.context_window,
        )
    else:
        console.print(f"[red]Error: backend '{settings.backend}' は未対応です（Phase 2 予定）[/red]")
        sys.exit(1)

    return Agent(
        backend=backend,
        dispatcher=ToolDispatcher(),
        max_steps=settings.agent.max_steps,
    )


def _run_with_ui(agent: Agent, user_input: str) -> None:
    chunks: list[str] = []
    spinner = Spinner("dots", text=" Thinking…", style="dim")

    with Live(spinner, console=console, refresh_per_second=15) as live:

        def on_text_chunk(chunk: str) -> None:
            chunks.append(chunk)
            live.update(Text("".join(chunks)))

        def on_tool_call(name: str, args: dict) -> None:
            if chunks:
                console.print(Text("".join(chunks)))
                chunks.clear()
            args_str = ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items())
            console.print(f"\n  [cyan]●[/cyan] [bold cyan]{name}[/bold cyan]({args_str})")
            live.update(spinner)

        def on_tool_result(name: str, result: str) -> None:
            if name == "task_done":
                return
            lines = result.splitlines()
            for line in lines[:4]:
                console.print(f"  [dim]│[/dim] {line}")
            if len(lines) > 4:
                console.print(f"  [dim]│ … ({len(lines) - 4} more lines)[/dim]")
            console.print()

        agent.on_tool_call = on_tool_call
        agent.on_tool_result = on_tool_result

        result = agent.run(user_input, on_text_chunk=on_text_chunk)

        if chunks:
            live.update(Text("".join(chunks)))
        elif result:
            live.update(Text(result))

    console.print()


def main() -> None:
    settings = load_settings()

    model_label = settings.ollama.model if settings.backend == "ollama" else settings.backend
    console.print(Panel(
        f"[bold cyan]StandAlone LLM Agent[/bold cyan]  [dim]{model_label}[/dim]\n"
        "[dim]Enter で改行 / Shift+Enter で送信 | '/reset' でリセット | 'exit' で終了[/dim]",
        border_style="cyan",
    ))

    if settings.backend == "ollama":
        probe = OllamaBackend(base_url=settings.ollama.base_url, model=settings.ollama.model)
        if not probe.is_available():
            console.print(f"[red]Error: Ollama が起動していません ({settings.ollama.base_url})[/red]")
            console.print("[yellow]  $ ollama serve  でOllamaを起動してから再実行してください[/yellow]")
            sys.exit(1)

    agent = _make_agent(settings)
    session = _build_session()

    while True:
        try:
            user_input = session.prompt()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]終了します[/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input.lower() == "exit":
            break
        if user_input == "/reset":
            agent.reset()
            console.print("[dim]会話をリセットしました[/dim]")
            continue

        try:
            _run_with_ui(agent, user_input)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


if __name__ == "__main__":
    main()
