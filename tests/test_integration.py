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


# ---------------------------------------------------------------------------
# 複雑なアプリ作成テスト
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_agent_creates_bank_account_class(ollama_backend, workdir):
    """複数メソッド・バリデーション付きのクラスを一から作成できることを確認する。

    シナリオ: BankAccount クラスを持つ bank_account.py を作成させる。
    - deposit / withdraw / get_balance の3メソッド
    - deposit・withdraw は amount <= 0 で ValueError
    - withdraw は残高不足で ValueError
    """
    import subprocess
    agent = _make_agent(ollama_backend, max_steps=20)
    agent.run(
        "bank_account.py を write_file で作成してください。\n"
        "以下の BankAccount クラスを実装してください:\n"
        "  - __init__(self): balance を 0 に初期化\n"
        "  - deposit(self, amount): amount <= 0 なら ValueError。それ以外は balance に加算\n"
        "  - withdraw(self, amount): amount <= 0 または balance 未満なら ValueError。それ以外は balance から減算\n"
        "  - get_balance(self): 現在の balance を返す\n"
        "作成後 bash で以下を実行して動作確認してください:\n"
        "python -c \""
        "from bank_account import BankAccount; "
        "acc = BankAccount(); "
        "acc.deposit(1000); "
        "acc.withdraw(300); "
        "assert acc.get_balance() == 700, acc.get_balance(); "
        "print('OK')"
        "\""
    )

    target = workdir / "bank_account.py"
    assert target.exists(), "bank_account.py が作成されていない"

    proc = subprocess.run(
        ["python", "-c",
         "from bank_account import BankAccount; "
         "acc = BankAccount(); "
         "acc.deposit(500); acc.withdraw(200); "
         "assert acc.get_balance() == 300; "
         # deposit with invalid amount should raise
         "raised = False\n"
         "try:\n"
         "    acc.deposit(-1)\n"
         "except ValueError:\n"
         "    raised = True\n"
         "assert raised"],
        capture_output=True, text=True, cwd=str(workdir),
    )
    assert proc.returncode == 0, (
        f"BankAccount の動作が正しくない:\n{proc.stderr}"
    )


@pytest.mark.integration
def test_agent_creates_word_counter(ollama_backend, workdir):
    """複数の関連する関数を持つモジュールを作成できることを確認する。

    シナリオ: テキスト解析モジュール word_counter.py を作成させる。
    - count_words(text): 各単語の出現回数を dict で返す（小文字統一）
    - top_n(text, n): 出現頻度上位 n 件を (word, count) のリストで返す
    """
    import subprocess
    agent = _make_agent(ollama_backend, max_steps=20)
    agent.run(
        "word_counter.py を write_file で作成してください。\n"
        "以下の関数を実装してください:\n"
        "  - count_words(text: str) -> dict: テキスト内の各単語の出現回数を返す（小文字に統一、句読点は無視）\n"
        "  - top_n(text: str, n: int) -> list: 出現回数の多い順に n 個の (word, count) タプルのリストを返す\n"
        "作成後 bash で以下を実行して動作確認してください:\n"
        "python -c \""
        "from word_counter import count_words, top_n; "
        "r = count_words('the cat sat on the mat the cat'); "
        "assert r['the'] == 3, r; "
        "assert r['cat'] == 2, r; "
        "t = top_n('a a a b b c', 2); "
        "assert t[0][0] == 'a', t; "
        "assert len(t) == 2, t; "
        "print('OK')"
        "\""
    )

    target = workdir / "word_counter.py"
    assert target.exists(), "word_counter.py が作成されていない"

    proc = subprocess.run(
        ["python", "-c",
         "from word_counter import count_words, top_n; "
         "r = count_words('hello world hello'); "
         "assert r.get('hello') == 2, r; "
         "t = top_n('x x x y y z', 1); "
         "assert t[0][0] == 'x', t"],
        capture_output=True, text=True, cwd=str(workdir),
    )
    assert proc.returncode == 0, (
        f"word_counter の動作が正しくない:\n{proc.stderr}"
    )


# ---------------------------------------------------------------------------
# 長い指示による改修テスト
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_agent_refactors_with_long_instructions(ollama_backend, workdir):
    """複数の改修要件を含む長い指示に従ってファイルを改修できることを確認する。

    シナリオ: バリデーションなし・型ヒントなしの stats.py に対して
    1. 空リスト渡しで ValueError を raise する入力検証を追加
    2. 全統計値を一度に返す summary() 関数を追加
    """
    import subprocess
    target = workdir / "stats.py"
    target.write_text(
        "def mean(values):\n"
        "    return sum(values) / len(values)\n"
        "\n"
        "def minimum(values):\n"
        "    return min(values)\n"
        "\n"
        "def maximum(values):\n"
        "    return max(values)\n",
        encoding="utf-8",
    )

    agent = _make_agent(ollama_backend, max_steps=25)
    agent.run(
        "stats.py を read_file で読み込んでください。\n"
        "以下の改修をすべて行ってください:\n"
        "\n"
        "1. mean / minimum / maximum の各関数の先頭に入力検証を追加する。\n"
        "   values が空リスト（len == 0）の場合は ValueError('values must not be empty') を raise すること。\n"
        "\n"
        "2. 以下のシグネチャで summary 関数を追加する:\n"
        "   def summary(values) -> dict:\n"
        "       mean, min, max をキーに持つ辞書を返す\n"
        "       例: summary([1, 2, 3]) == {'mean': 2.0, 'min': 1, 'max': 3}\n"
        "\n"
        "修正後 bash で以下を実行してエラーが出ないことを確認してください:\n"
        "python -c \""
        "from stats import mean, minimum, maximum, summary; "
        "assert mean([1,2,3]) == 2.0; "
        "assert minimum([3,1,2]) == 1; "
        "assert maximum([3,1,2]) == 3; "
        "s = summary([1,2,3]); "
        "assert s['mean'] == 2.0 and s['min'] == 1 and s['max'] == 3; "
        "print('OK')"
        "\""
    )

    src = target.read_text(encoding="utf-8")
    assert "summary" in src, f"summary 関数が追加されていない:\n{src}"
    assert "ValueError" in src, f"入力検証が追加されていない:\n{src}"

    proc = subprocess.run(
        ["python", "-c",
         "from stats import mean, summary; "
         # 既存関数が動作すること
         "assert mean([10, 20, 30]) == 20.0; "
         # summary が正しく動作すること
         "s = summary([2, 4, 6]); "
         "assert s['mean'] == 4.0 and s['min'] == 2 and s['max'] == 6; "
         # 空リストで ValueError が発生すること
         "ok = False\n"
         "try:\n"
         "    mean([])\n"
         "except ValueError:\n"
         "    ok = True\n"
         "assert ok, 'ValueError が発生しなかった'"],
        capture_output=True, text=True, cwd=str(workdir),
    )
    assert proc.returncode == 0, (
        f"改修後の stats.py が正しく動作しない:\n{proc.stderr}"
    )


# ---------------------------------------------------------------------------
# 複数ファイル改修テスト
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_agent_adds_feature_across_two_files(ollama_backend, workdir):
    """2ファイルを連携して修正し、新機能を追加できることを確認する。

    シナリオ:
    - geometry.py: circle_area / rectangle_area を定義
    - report.py  : geometry をインポートして面積を出力
    geometry.py に triangle_area(base, height) を追加し、
    report.py からも呼び出すよう修正させる。
    """
    import subprocess
    (workdir / "geometry.py").write_text(
        "import math\n"
        "\n"
        "def circle_area(r):\n"
        "    return math.pi * r * r\n"
        "\n"
        "def rectangle_area(w, h):\n"
        "    return w * h\n",
        encoding="utf-8",
    )
    (workdir / "report.py").write_text(
        "from geometry import circle_area, rectangle_area\n"
        "\n"
        "print(f'circle  : {circle_area(5):.2f}')\n"
        "print(f'rectangle: {rectangle_area(4, 6)}')\n",
        encoding="utf-8",
    )

    agent = _make_agent(ollama_backend, max_steps=25)
    agent.run(
        "geometry.py と report.py を read_file でそれぞれ読み込んでください。\n"
        "以下の変更をすべて行ってください:\n"
        "\n"
        "1. geometry.py に triangle_area(base, height) 関数を追加する。\n"
        "   計算式: base * height / 2\n"
        "\n"
        "2. report.py を修正して triangle_area をインポートし、\n"
        "   triangle_area(6, 8) の結果も出力するようにする。\n"
        "\n"
        "修正後 bash で python report.py を実行して3行分の出力が得られることを確認してください。"
    )

    geo_src = (workdir / "geometry.py").read_text(encoding="utf-8")
    assert "triangle_area" in geo_src, f"triangle_area が geometry.py に追加されていない:\n{geo_src}"

    rep_src = (workdir / "report.py").read_text(encoding="utf-8")
    assert "triangle_area" in rep_src, f"triangle_area が report.py から呼ばれていない:\n{rep_src}"

    proc = subprocess.run(
        ["python", "report.py"], capture_output=True, text=True, cwd=str(workdir),
    )
    assert proc.returncode == 0, f"report.py がクラッシュした:\n{proc.stderr}"
    assert proc.stdout.count("\n") >= 3, (
        f"出力が3行未満:\n{proc.stdout!r}"
    )

    # triangle_area の計算が正しいことを直接検証
    proc2 = subprocess.run(
        ["python", "-c",
         "from geometry import triangle_area; "
         "assert triangle_area(6, 8) == 24.0, triangle_area(6, 8)"],
        capture_output=True, text=True, cwd=str(workdir),
    )
    assert proc2.returncode == 0, (
        f"triangle_area の計算が正しくない:\n{proc2.stderr}"
    )


@pytest.mark.integration
def test_agent_renames_function_across_multiple_files(ollama_backend, workdir):
    """複数ファイルにまたがる関数リネームが一貫して行えることを確認する。

    シナリオ:
    - utils.py  : calc_tax(price, rate) を定義
    - invoice.py: calc_tax をインポートして使用
    calc_tax を calculate_tax にリネームさせる。
    """
    import subprocess
    (workdir / "utils.py").write_text(
        "def calc_tax(price, rate):\n"
        "    return price * rate / 100\n",
        encoding="utf-8",
    )
    (workdir / "invoice.py").write_text(
        "from utils import calc_tax\n"
        "\n"
        "def print_invoice(price, rate):\n"
        "    tax = calc_tax(price, rate)\n"
        "    print(f'price={price}, tax={tax:.2f}, total={price + tax:.2f}')\n"
        "\n"
        "print_invoice(1000, 10)\n",
        encoding="utf-8",
    )

    agent = _make_agent(ollama_backend, max_steps=25)
    agent.run(
        "utils.py と invoice.py を read_file でそれぞれ読み込んでください。\n"
        "関数名 calc_tax をすべての箇所で calculate_tax にリネームしてください。\n"
        "変更が必要な箇所:\n"
        "  - utils.py の関数定義 (def calc_tax)\n"
        "  - invoice.py の import 文 (from utils import calc_tax)\n"
        "  - invoice.py の呼び出し箇所 (calc_tax(...))\n"
        "変更後 bash で python invoice.py を実行してエラーが出ないことを確認してください。"
    )

    utils_src = (workdir / "utils.py").read_text(encoding="utf-8")
    invoice_src = (workdir / "invoice.py").read_text(encoding="utf-8")

    assert "calculate_tax" in utils_src, f"utils.py でリネームされていない:\n{utils_src}"
    assert "calc_tax" not in utils_src, f"utils.py に古い名前が残っている:\n{utils_src}"
    assert "calculate_tax" in invoice_src, f"invoice.py でリネームされていない:\n{invoice_src}"
    assert "calc_tax" not in invoice_src, f"invoice.py に古い名前が残っている:\n{invoice_src}"

    proc = subprocess.run(
        ["python", "invoice.py"], capture_output=True, text=True, cwd=str(workdir),
    )
    assert proc.returncode == 0, f"invoice.py がクラッシュした:\n{proc.stderr}"
    assert "total=" in proc.stdout, f"期待する出力が得られなかった:\n{proc.stdout!r}"


@pytest.mark.integration
def test_agent_creates_multifile_app_in_subdir(ollama_backend, workdir):
    """サブディレクトリに複数ファイルを作成し、sibling import が正しく動作することを確認する。

    シナリオ: tmp/ ディレクトリ内に models.py と main.py を作成させる。
    main.py は models.py をインポートして使う。
    エージェントが `cd tmp && python main.py` のように実行すれば成功。
    `python tmp/main.py` だと ModuleNotFoundError になるはずのシナリオ。
    """
    import subprocess

    agent = _make_agent(ollama_backend, max_steps=20)
    agent.run(
        f"作業ディレクトリ: {workdir}\n"
        f"{workdir}/tmp ディレクトリ内に以下の2ファイルを作成してください:\n"
        "\n"
        "1. models.py:\n"
        "   class Item:\n"
        "       def __init__(self, name, price):\n"
        "           self.name = name\n"
        "           self.price = price\n"
        "       def __repr__(self):\n"
        "           return f'Item({self.name!r}, {self.price})'\n"
        "\n"
        "2. main.py (models.py をインポートして使う):\n"
        "   from models import Item\n"
        "   items = [Item('apple', 100), Item('banana', 80)]\n"
        "   for item in items:\n"
        "       print(item)\n"
        "\n"
        "作成後、bash で実行して動作確認してください。"
    )

    tmp = workdir / "tmp"
    assert tmp.exists(), "tmp/ ディレクトリが作成されていない"
    assert (tmp / "models.py").exists(), "tmp/models.py が作成されていない"
    assert (tmp / "main.py").exists(), "tmp/main.py が作成されていない"

    main_src = (tmp / "main.py").read_text(encoding="utf-8")
    assert "models" in main_src, f"main.py が models をインポートしていない:\n{main_src}"

    proc = subprocess.run(
        ["python", "main.py"], capture_output=True, text=True, cwd=str(tmp),
    )
    assert proc.returncode == 0, (
        f"python main.py がクラッシュした (cwd=tmp):\n{proc.stderr}"
    )
    assert "apple" in proc.stdout or "Item" in proc.stdout, (
        f"期待する出力が得られなかった:\n{proc.stdout!r}"
    )
