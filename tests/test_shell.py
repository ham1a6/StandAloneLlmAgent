import sys
import tools.shell
from tools.shell import bash

# quoted パス形式でテスト (PowerShell では & プレフィクス自動付与を確認)
_PY_QUOTED = f'"{sys.executable}"'
# bare コマンド形式でテスト (venv の python が PATH に入っている前提)
_PY = "python"


def test_bash_basic_output():
    result = bash(f'{_PY_QUOTED} -c "print(42)"')
    assert "42" in result


def test_bash_nonzero_exit_code():
    result = bash(f'{_PY_QUOTED} -c "import sys; sys.exit(1)"')
    assert "exit code: 1" in result


def test_bash_no_output():
    result = bash(f'{_PY_QUOTED} -c "pass"')
    assert result == "(no output)"


def test_bash_stderr_captured():
    result = bash(f'{_PY} -c "import sys; sys.stderr.write(\'err_msg\')"')
    assert "err_msg" in result


def test_bash_timeout():
    result = bash(f'{_PY_QUOTED} -c "import time; time.sleep(100)"', timeout=1)
    assert "timed out" in result


def test_bash_multiline_output():
    result = bash(f'{_PY} -c "print(1); print(2); print(3)"')
    assert "1" in result
    assert "2" in result
    assert "3" in result
