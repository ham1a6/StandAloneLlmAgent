"""
Integration tests — require Ollama to be running.

Run:
    pytest tests/test_integration.py -v
    pytest -m integration -v

Ollama が起動していない場合は自動的にスキップされます。
"""
from __future__ import annotations
import pytest
import tools  # noqa: F401 — registers all tools at import time


@pytest.fixture(scope="module")
def ollama_backend():
    from backends.ollama import OllamaBackend
    from config.settings import load_settings

    settings = load_settings()
    backend = OllamaBackend(
        base_url=settings.ollama.base_url,
        model=settings.ollama.model,
        temperature=0.1,  # 低めに設定して出力を安定させる
        context_window=settings.ollama.context_window,
    )
    if not backend.is_available():
        pytest.skip("Ollama が起動していません。`ollama serve` を実行してから再試行してください。")
    return backend


def _make_agent(backend, max_steps: int = 15):
    from tools.registry import ToolDispatcher
    from agent.core import Agent

    return Agent(backend=backend, dispatcher=ToolDispatcher(), max_steps=max_steps)


@pytest.mark.integration
def test_ollama_connection(ollama_backend):
    """Ollama サーバーに接続できることを確認する"""
    assert ollama_backend.is_available()


@pytest.mark.integration
def test_agent_creates_file(ollama_backend, tmp_path, monkeypatch):
    """エージェントが write_file ツールでファイルを作成できる"""
    monkeypatch.chdir(tmp_path)
    agent = _make_agent(ollama_backend)

    agent.run("hello.txt を write_file で作成して、'Hello, World!' とだけ書き込んでください")

    target = tmp_path / "hello.txt"
    assert target.exists(), "hello.txt が作成されていない"
    content = target.read_text(encoding="utf-8")
    assert len(content) > 0, "hello.txt の内容が空"
    assert "Hello" in content, f"期待する文字列が含まれていない: {content!r}"


@pytest.mark.integration
def test_agent_generates_and_runs_python(ollama_backend, tmp_path, monkeypatch):
    """エージェントが Python スクリプトを生成・実行できる"""
    monkeypatch.chdir(tmp_path)
    agent = _make_agent(ollama_backend)

    agent.run(
        "fizzbuzz.py を write_file で作成してください。"
        "1 から 15 まで FizzBuzz を出力するスクリプトです。"
        "作成後 bash で python fizzbuzz.py を実行して出力を確認してください。"
    )

    target = tmp_path / "fizzbuzz.py"
    assert target.exists(), "fizzbuzz.py が作成されていない"
    src = target.read_text(encoding="utf-8")
    assert len(src) > 20, f"fizzbuzz.py の内容が短すぎる: {src!r}"


@pytest.mark.integration
def test_agent_reads_and_edits_file(ollama_backend, tmp_path, monkeypatch):
    """エージェントが既存ファイルを read_file で読んでから edit_file で修正できる"""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "counter.py"
    target.write_text('COUNT = 0\nprint(COUNT)\n', encoding="utf-8")

    agent = _make_agent(ollama_backend)
    agent.run(
        "counter.py の COUNT を 42 に変更してください。"
        "read_file で内容を確認してから edit_file で修正してください。"
    )

    result_src = target.read_text(encoding="utf-8")
    assert "42" in result_src, f"COUNT が 42 に変更されていない: {result_src!r}"
