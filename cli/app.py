from __future__ import annotations
import sys
from typing import Callable
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

import tools  # noqa: F401 — registers all tools at import time
from config.settings import load_settings, Settings
from backends.ollama import OllamaBackend
from tools.registry import ToolDispatcher
from agent.core import Agent

console = Console()

_CONFIRM_SHELL_TOOLS = {"bash"}
_CONFIRM_WRITE_TOOLS = {"write_file", "edit_file"}


def _build_confirm(settings: Settings) -> Callable[[str, dict], bool] | None:
    shell_confirm = settings.permissions.require_confirm_before_shell
    write_confirm = settings.permissions.require_confirm_before_write

    if not shell_confirm and not write_confirm:
        return None

    def on_confirm(name: str, args: dict) -> bool:
        if shell_confirm and name in _CONFIRM_SHELL_TOOLS:
            pass
        elif write_confirm and name in _CONFIRM_WRITE_TOOLS:
            pass
        else:
            return True

        cmd_preview = args.get("command") or args.get("path") or ""
        if cmd_preview:
            console.print(f"  [yellow]?[/yellow] [bold yellow]{name}[/bold yellow]: {cmd_preview[:120]}")
        answer = console.input("  [yellow]実行しますか? [y/N][/yellow] ")
        return answer.strip().lower() in ("y", "yes")

    return on_confirm


def _build_session(auto_mode: list[bool]) -> PromptSession:
    kb = KeyBindings()

    # Enter = submit (overrides multiline default of inserting newline)
    @kb.add("enter", eager=True)
    def _submit(event):
        event.current_buffer.validate_and_handle()

    def _insert_newline(event):
        event.current_buffer.insert_text("\n")

    # Shift+Enter — terminals send different escape sequences:
    #   \x1b[27;2;13~  Windows Terminal / xterm with modifyOtherKeys
    #   \x1b[13;2u     Kitty keyboard protocol
    for _seq in ("\x1b[27;2;13~", "\x1b[13;2u"):
        try:
            kb.add(_seq)(_insert_newline)
        except Exception:
            pass

    # Alt+Enter = newline (cross-terminal fallback)
    @kb.add("escape", "enter")
    def _newline_alt(event):
        event.current_buffer.insert_text("\n")

    # Shift+Tab (BackTab) = toggle Edit automatically mode
    @kb.add(Keys.BackTab)
    def _toggle_auto(event):
        auto_mode[0] = not auto_mode[0]
        if auto_mode[0]:
            console.print(
                "\n  [bold yellow]⚡ Edit automatically: ON[/bold yellow]"
                "  [dim](確認なしで自動実行)[/dim]"
            )
        else:
            console.print(
                "\n  [dim]⚡ Edit automatically: OFF[/dim]"
                "  [dim](通常の確認モード)[/dim]"
            )
        event.app.invalidate()

    def _get_prompt():
        if auto_mode[0]:
            return HTML(
                "<ansiyellow><b>[AUTO] </b></ansiyellow>"
                "<ansigreen><b>&gt;</b></ansigreen> "
            )
        return HTML("<ansigreen><b>&gt;</b></ansigreen> ")

    return PromptSession(
        message=_get_prompt,
        multiline=True,
        key_bindings=kb,
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
        console.print(f"[red]Error: backend '{settings.backend}' は未対応です[/red]")
        sys.exit(1)

    return Agent(
        backend=backend,
        dispatcher=ToolDispatcher(),
        max_steps=settings.agent.max_steps,
        on_confirm=_build_confirm(settings),
    )


def _run_with_ui(agent: Agent, user_input: str, auto_mode: list[bool]) -> None:
    chunks: list[str] = []
    spinner = Spinner("dots", text=" Thinking…", style="dim")
    # Preserve the settings-based confirm; bypass it entirely in auto mode
    _original_confirm = agent.on_confirm
    _effective_confirm = None if auto_mode[0] else _original_confirm

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

        def on_confirm_in_live(name: str, args: dict) -> bool:
            # Pause Live rendering while the user answers the confirmation prompt
            live.stop()
            try:
                return _effective_confirm(name, args)
            finally:
                live.start()

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
        agent.on_confirm = on_confirm_in_live if _effective_confirm else None

        try:
            result = agent.run(user_input, on_text_chunk=on_text_chunk)
        finally:
            agent.on_confirm = _original_confirm

        if chunks:
            live.update(Text("".join(chunks)))
        elif result:
            live.update(Text(result))
        else:
            live.update(Text("[dim](モデルからの応答がありませんでした)[/dim]"))

    console.print()


def main() -> None:
    settings = load_settings()
    auto_mode = [False]  # list so closures can mutate it

    model_label = settings.ollama.model if settings.backend == "ollama" else settings.backend
    console.print(Panel(
        f"[bold cyan]StandAlone LLM Agent[/bold cyan]  [dim]{model_label}[/dim]\n"
        "[dim]Enter で送信  Shift+Enter で改行  Shift+Tab で自動実行モード切替\n"
        "追加プロンプトで生成したアプリを修正可能  '/reset' でリセット  'exit' で終了[/dim]",
        border_style="cyan",
    ))

    if settings.backend == "ollama":
        probe = OllamaBackend(base_url=settings.ollama.base_url, model=settings.ollama.model)
        if not probe.is_available():
            console.print(f"[red]Error: Ollama が起動していません ({settings.ollama.base_url})[/red]")
            console.print("[yellow]  $ ollama serve  でOllamaを起動してから再実行してください[/yellow]")
            sys.exit(1)

    session = _build_session(auto_mode)
    agent = _make_agent(settings)

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
            _run_with_ui(agent, user_input, auto_mode)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


if __name__ == "__main__":
    main()
