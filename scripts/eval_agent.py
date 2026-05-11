"""
Manual evaluation script for StandAlone LLM Agent.

Runs predefined prompts and shows the full agent UI output for visual inspection.
After each test, enter [p]ass / [f]ail / [s]kip to record the result.

Usage:
    python -m scripts.eval_agent
    python -m scripts.eval_agent --cases 1,3,5
"""
from __future__ import annotations
import os
import sys
import argparse
import shutil
import tempfile
from pathlib import Path

# Ensure project root is importable regardless of invocation directory
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import tools  # noqa: F401 — registers all tools before ToolDispatcher()
import tools.shell as _shell_mod
from config.settings import load_settings
from backends.ollama import OllamaBackend
from tools.registry import ToolDispatcher
from agent.core import Agent
from cli.app import _run_with_ui, console

from rich.panel import Panel
from rich.rule import Rule


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

TEST_CASES = [
    {
        "id": 1,
        "name": "FizzBuzz 生成・実行",
        "prompt": (
            "1 から 30 までの FizzBuzz を出力する Python スクリプト fizzbuzz.py を作成し、"
            "実行して結果を確認してください。"
        ),
    },
    {
        "id": 2,
        "name": "ファイル集計パイプライン",
        "prompt": (
            "scores.txt というファイルに 10 行の整数（50〜100 の範囲でバリエーション豊かに）を書き込んでください。"
            "次にそのファイルを読み込み、平均・最大・最小を計算して summary.txt に出力してください。"
            "最後に summary.txt の内容を確認して報告してください。"
        ),
    },
    {
        "id": 3,
        "name": "バグ修正サイクル",
        "prompt": (
            "1 から 20 の素数をすべて出力する Python スクリプト primes.py を書いてください。"
            "スクリプトを実行し、エラーが出た場合は修正して正しい結果（2 3 5 7 11 13 17 19）が"
            "得られるまで繰り返してください。"
        ),
    },
    {
        "id": 4,
        "name": "JSON 生成・集計・出力",
        "prompt": (
            "5 人の社員データ（name, department, score）を持つ JSON ファイル employees.json を作成してください"
            "（部署は Sales / Engineering / HR のいずれか、スコアは 60〜100）。"
            "次にそのファイルを読み込み、部署ごとの平均スコアを計算し、"
            "スコアの高い順に並べた結果を report.txt に書き出してください。"
        ),
    },
    {
        "id": 5,
        "name": "ディレクトリ構造の構築と検証",
        "prompt": (
            "以下の構造を作成してください：\n"
            "  project/\n"
            "    src/main.py  （Hello World を print するスクリプト）\n"
            "    tests/test_main.py  （main.py を import して出力が 'Hello World' であることを assert するテスト）\n"
            "    README.txt  （プロジェクトの説明を 3 行で）\n"
            "作成後、python project/src/main.py を実行して動作確認し、"
            "python -m pytest project/tests/ を実行してテストが通ることを確認してください。"
        ),
    },
    {
        "id": 6,
        "name": "cd 状態引き継ぎ確認",
        "prompt": (
            "work というディレクトリを作成して cd してください。"
            "そのディレクトリ内に hello.txt を作成し（内容は 'cd works!'）、"
            "ファイルを読み込んで内容を確認してください。"
            "最後に現在のディレクトリのパスも教えてください。"
        ),
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_agent(settings, tmp_dir: str) -> Agent:
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
    )


def _list_created_files(tmp_dir: str) -> list[str]:
    base = Path(tmp_dir)
    return sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())


def _ask_verdict(test_id: int) -> str:
    while True:
        try:
            raw = input(f"\n  Test {test_id} の結果 → [p]ass / [f]ail / [s]kip : ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return "abort"
        if raw in ("p", "pass", ""):
            return "PASS"
        if raw in ("f", "fail"):
            return "FAIL"
        if raw in ("s", "skip"):
            return "SKIP"


def _print_summary(results: list[tuple[int, str, str]]) -> None:
    if not results:
        return
    console.print()
    console.print(Rule("[bold]評価サマリー[/bold]", style="cyan"))
    color_map = {"PASS": "green", "FAIL": "red", "SKIP": "yellow"}
    for test_id, name, verdict in results:
        c = color_map.get(verdict, "white")
        console.print(f"  Test {test_id:>2}: [{c}]{verdict}[/{c}]  {name}")
    passed = sum(1 for _, _, v in results if v == "PASS")
    failed = sum(1 for _, _, v in results if v == "FAIL")
    console.print()
    console.print(f"  [bold]{passed} PASS  {failed} FAIL  {len(results) - passed - failed} SKIP[/bold]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Agent manual evaluation")
    parser.add_argument(
        "--cases", metavar="IDs",
        help="実行するテストケース番号をカンマ区切りで指定（例: --cases 1,3,5）",
    )
    args = parser.parse_args()

    case_ids: set[int] | None = None
    if args.cases:
        case_ids = {int(x.strip()) for x in args.cases.split(",")}

    cases = [tc for tc in TEST_CASES if case_ids is None or tc["id"] in case_ids]
    if not cases:
        console.print("[red]指定されたテストケースが見つかりません[/red]")
        sys.exit(1)

    # Load settings once (uses CWD-relative settings.yaml; do it before any chdir)
    original_cwd = os.getcwd()
    settings_path = str(_ROOT / "settings.yaml")
    settings = load_settings(settings_path)

    model_label = settings.ollama.model if settings.backend == "ollama" else settings.backend
    console.print(Panel(
        f"[bold cyan]Agent Manual Eval[/bold cyan]  [dim]{model_label}[/dim]\n"
        f"[dim]{len(cases)} テストケースを順に実行します。"
        "各テスト後に Pass/Fail/Skip を入力してください。[/dim]",
        border_style="cyan",
    ))

    if settings.backend == "ollama":
        probe = OllamaBackend(base_url=settings.ollama.base_url, model=settings.ollama.model)
        if not probe.is_available():
            console.print(f"[red]Error: Ollama が起動していません ({settings.ollama.base_url})[/red]")
            sys.exit(1)

    results: list[tuple[int, str, str]] = []

    for tc in cases:
        console.print()
        console.print(Rule(
            f"[bold]Test {tc['id']}/{len(TEST_CASES)}: {tc['name']}[/bold]",
            style="cyan",
        ))

        tmp_dir = tempfile.mkdtemp(prefix=f"eval_{tc['id']}_")
        try:
            # Point both the process CWD and the shell tool's internal CWD at tmp_dir
            os.chdir(tmp_dir)
            _shell_mod._set_cwd(tmp_dir)

            console.print(f"[dim]作業ディレクトリ: {tmp_dir}[/dim]")
            console.print()

            agent = _build_agent(settings, tmp_dir)

            try:
                _run_with_ui(agent, tc["prompt"])
            except Exception as e:
                console.print(f"[red]エージェント実行エラー: {e}[/red]")

            # Diagnostic summary
            console.print()
            created = _list_created_files(tmp_dir)
            if created:
                console.print(f"[dim]生成されたファイル ({len(created)}件):[/dim]")
                for f in created:
                    console.print(f"  [dim]  {f}[/dim]")
            else:
                console.print("[dim](ファイルは作成されませんでした)[/dim]")

            # Context inspection: count tool calls from message history
            tool_msgs = [m for m in agent.context.get_messages() if m.role == "assistant" and m.tool_calls]
            total_tool_calls = sum(len(m.tool_calls) for m in tool_msgs)
            if total_tool_calls == 0:
                console.print(
                    "[yellow]⚠  ツール呼び出しなし[/yellow] "
                    "[dim]— モデルがテキスト回答のみを返しました[/dim]"
                )
                console.print(
                    "[dim]   hint: function calling に対応したモデル"
                    "（例: qwen2.5-coder:7b）を試してください[/dim]"
                )

        finally:
            os.chdir(original_cwd)
            _shell_mod._set_cwd(original_cwd)
            shutil.rmtree(tmp_dir, ignore_errors=True)

        verdict = _ask_verdict(tc["id"])
        if verdict == "abort":
            console.print("\n[dim]中断しました[/dim]")
            _print_summary(results)
            return
        results.append((tc["id"], tc["name"], verdict))

    _print_summary(results)


if __name__ == "__main__":
    main()
