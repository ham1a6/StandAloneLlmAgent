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
def test_agent_creates_file(ollama_backend, workdir):
    """エージェントが write_file ツールでファイルを作成できる"""
    agent = _make_agent(ollama_backend)

    agent.run("hello.txt を write_file で作成して、'Hello, World!' とだけ書き込んでください")

    target = workdir / "hello.txt"
    assert target.exists(), "hello.txt が作成されていない"
    content = target.read_text(encoding="utf-8")
    assert len(content) > 0, "hello.txt の内容が空"
    assert "Hello" in content, f"期待する文字列が含まれていない: {content!r}"


@pytest.mark.integration
def test_agent_generates_and_runs_python(ollama_backend, workdir):
    """エージェントが Python スクリプトを生成・実行できる"""
    agent = _make_agent(ollama_backend)

    agent.run(
        "fizzbuzz.py を write_file で作成してください。"
        "1 から 15 まで FizzBuzz を出力するスクリプトです。"
        "作成後 bash で python fizzbuzz.py を実行して出力を確認してください。"
    )

    target = workdir / "fizzbuzz.py"
    assert target.exists(), "fizzbuzz.py が作成されていない"
    src = target.read_text(encoding="utf-8")
    assert len(src) > 20, f"fizzbuzz.py の内容が短すぎる: {src!r}"


@pytest.mark.integration
def test_agent_reads_and_edits_file(ollama_backend, workdir):
    """エージェントが既存ファイルを read_file で読んでから edit_file で修正できる"""
    target = workdir / "counter.py"
    target.write_text('COUNT = 0\nprint(COUNT)\n', encoding="utf-8")

    agent = _make_agent(ollama_backend)
    agent.run(
        "counter.py の COUNT を 42 に変更してください。"
        "read_file で内容を確認してから edit_file で修正してください。"
    )

    result_src = target.read_text(encoding="utf-8")
    assert "42" in result_src, f"COUNT が 42 に変更されていない: {result_src!r}"


# ---------------------------------------------------------------------------
# ファイル修正・改修テスト
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_agent_fixes_runtime_bug(ollama_backend, workdir):
    """バグのあるコードを読み込んで修正し、正常に動作することを確認する。

    シナリオ: divide(10, 0) で ZeroDivisionError が起きる関数を
    b==0 のとき None を返すよう修正させる。
    """
    import subprocess
    target = workdir / "calc.py"
    target.write_text(
        "def divide(a, b):\n"
        "    return a / b\n"
        "\n"
        "print(divide(10, 2))\n"
        "print(divide(10, 0))\n",
        encoding="utf-8",
    )

    agent = _make_agent(ollama_backend)
    agent.run(
        "calc.py を read_file で読み込んでください。\n"
        "divide(10, 0) を呼ぶと ZeroDivisionError が発生するバグがあります。\n"
        "b が 0 のとき None を返すように修正してください。\n"
        "修正後 bash で python calc.py を実行してエラーが出ないことを確認してください。"
    )

    src = target.read_text(encoding="utf-8")
    assert "divide" in src, "divide 関数が消えている"

    proc = subprocess.run(
        ["python", str(target)], capture_output=True, text=True
    )
    assert proc.returncode == 0, (
        f"修正後もスクリプトがクラッシュしている:\n{proc.stderr}"
    )


@pytest.mark.integration
def test_agent_adds_function_to_existing(ollama_backend, workdir):
    """既存ファイルに新しい関数を追加し、既存関数が壊れていないことを確認する。

    シナリオ: add / subtract のみある math_utils.py に
    multiply 関数を追加させる。
    """
    import subprocess
    target = workdir / "math_utils.py"
    target.write_text(
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def subtract(a, b):\n"
        "    return a - b\n",
        encoding="utf-8",
    )

    agent = _make_agent(ollama_backend)
    agent.run(
        "math_utils.py を read_file で読み込んでください。\n"
        "multiply(a, b) 関数を追加してください（既存の add / subtract は変更不要）。\n"
        "追加後 bash で以下のコマンドを実行して動作確認してください:\n"
        "python -c \"from math_utils import add, subtract, multiply; "
        "print(add(1,2), subtract(5,3), multiply(3,4))\""
    )

    src = target.read_text(encoding="utf-8")
    assert "multiply" in src, f"multiply 関数が追加されていない:\n{src}"
    assert "add" in src, "add 関数が消えている"
    assert "subtract" in src, "subtract 関数が消えている"

    proc = subprocess.run(
        ["python", "-c",
         "from math_utils import add, subtract, multiply; "
         "assert multiply(3, 4) == 12"],
        capture_output=True, text=True, cwd=str(workdir),
    )
    assert proc.returncode == 0, (
        f"multiply の動作が正しくない:\n{proc.stderr}"
    )


@pytest.mark.integration
def test_agent_fixes_syntax_error(ollama_backend, workdir):
    """構文エラーのあるファイルを修正して正常に実行できることを確認する。

    シナリオ: 閉じ括弧が抜けた greeting.py を修正させる。
    """
    import subprocess
    target = workdir / "greeting.py"
    target.write_text(
        'def greet(name):\n'
        '    print("Hello, " + name\n'   # 閉じ括弧が抜けている
        '\n'
        'greet("World")\n',
        encoding="utf-8",
    )

    agent = _make_agent(ollama_backend)
    agent.run(
        "greeting.py を read_file で読み込んでください。\n"
        "構文エラーがあります。修正して python greeting.py を実行し、"
        "Hello が出力されることを確認してください。"
    )

    proc = subprocess.run(
        ["python", str(target)], capture_output=True, text=True
    )
    assert proc.returncode == 0, (
        f"修正後も構文エラーが残っている:\n{proc.stderr}"
    )
    assert "Hello" in proc.stdout, (
        f"期待する出力が得られなかった: {proc.stdout!r}"
    )


@pytest.mark.integration
def test_agent_renames_variable_consistently(ollama_backend, workdir):
    """ファイル内の変数名を全箇所で一貫してリネームできることを確認する。

    シナリオ: MAX_SIZE を使っている config.py の変数を MAX_LIMIT に変更させる。
    """
    import subprocess
    target = workdir / "config.py"
    target.write_text(
        "MAX_SIZE = 100\n"
        "\n"
        "def check(value):\n"
        "    if value > MAX_SIZE:\n"
        '        raise ValueError(f"exceeds MAX_SIZE={MAX_SIZE}")\n'
        "    return True\n"
        "\n"
        "print(MAX_SIZE)\n"
        "print(check(50))\n",
        encoding="utf-8",
    )

    agent = _make_agent(ollama_backend)
    agent.run(
        "config.py を read_file で読み込んでください。\n"
        "変数名 MAX_SIZE をすべて MAX_LIMIT にリネームしてください。\n"
        "定義・参照・文字列内すべてを変更すること。\n"
        "変更後 bash で python config.py を実行してエラーが出ないことを確認してください。"
    )

    src = target.read_text(encoding="utf-8")
    assert "MAX_LIMIT" in src, f"MAX_LIMIT にリネームされていない:\n{src}"

    proc = subprocess.run(
        ["python", str(target)], capture_output=True, text=True
    )
    assert proc.returncode == 0, (
        f"リネーム後にスクリプトがクラッシュした:\n{proc.stderr}"
    )
