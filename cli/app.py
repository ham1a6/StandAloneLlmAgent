from __future__ import annotations
import sys
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

import tools  # noqa: F401 — must be imported before ToolDispatcher() to register all tools
from config.settings import load_settings, Settings
from backends.ollama import OllamaBackend
from tools.registry import ToolDispatcher
from agent.core import Agent

console = Console()


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

    dispatcher = ToolDispatcher()

    def on_tool_call(name: str, args: dict) -> None:
        args_str = ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items())
        console.print(f"  [dim cyan][Tool: {name}({args_str})][/dim cyan]")

    def on_tool_result(name: str, result: str) -> None:
        if name == "task_done":
            return
        lines = result.splitlines()
        preview = "\n    ".join(lines[:4])
        suffix = f"\n    [dim]... ({len(lines) - 4} more lines)[/dim]" if len(lines) > 4 else ""
        console.print(f"  [dim]→ {preview}{suffix}[/dim]")

    return Agent(
        backend=backend,
        dispatcher=dispatcher,
        max_steps=settings.agent.max_steps,
        on_tool_call=on_tool_call,
        on_tool_result=on_tool_result,
    )


def main() -> None:
    settings = load_settings()

    model_label = settings.ollama.model if settings.backend == "ollama" else settings.backend
    console.print(Panel(
        f"[bold cyan]StandAlone LLM Agent[/bold cyan]  [dim]{model_label}[/dim]\n"
        "[dim]'exit' または Ctrl+C で終了 | '/reset' で会話リセット[/dim]",
        border_style="cyan",
    ))

    if settings.backend == "ollama":
        probe = OllamaBackend(base_url=settings.ollama.base_url, model=settings.ollama.model)
        if not probe.is_available():
            console.print(f"[red]Error: Ollama が起動していません ({settings.ollama.base_url})[/red]")
            console.print("[yellow]  $ ollama serve  でOllamaを起動してから再実行してください[/yellow]")
            sys.exit(1)

    agent = _make_agent(settings)

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]>[/bold green]")
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

        console.print("[dim]Thinking...[/dim]")
        try:
            result = agent.run(user_input)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            continue

        console.print(f"\n[white]{result}[/white]")


if __name__ == "__main__":
    main()
