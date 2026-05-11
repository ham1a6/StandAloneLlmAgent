import platform
import subprocess
import os
import threading
from tools.registry import tool

_IS_WINDOWS = platform.system() == "Windows"
_CWD_MARKER = "__AGENT_CWD__:"

_cwd: str = os.getcwd()
_cwd_lock = threading.Lock()


def _get_cwd() -> str:
    with _cwd_lock:
        return _cwd


def _set_cwd(new_cwd: str) -> None:
    global _cwd
    with _cwd_lock:
        _cwd = new_cwd


def _split_cwd_marker(stdout: str) -> tuple[str, str | None]:
    """Remove __AGENT_CWD__: line from stdout and return (clean_output, new_cwd)."""
    lines = stdout.splitlines()
    clean: list[str] = []
    new_cwd: str | None = None
    for line in lines:
        if line.startswith(_CWD_MARKER):
            candidate = line[len(_CWD_MARKER):].strip()
            if os.path.isdir(candidate):
                new_cwd = candidate
        else:
            clean.append(line)
    return "\n".join(clean), new_cwd


@tool(name="bash", description="シェルコマンドを実行する（Windows は PowerShell、Unix は bash）。cd の効果は次の呼び出しにも引き継がれる")
def bash(command: str, timeout: int = 60) -> str:
    """
    command: 実行するシェルコマンド
    timeout: タイムアウト秒数
    """
    cwd = _get_cwd()
    try:
        if _IS_WINDOWS:
            cmd = command.strip()
            if cmd.startswith('"') or cmd.startswith("'"):
                cmd = f"& {cmd}"
            # Preserve original exit code; append CWD marker via Write-Output (captured in stdout)
            wrapped = (
                f'{cmd}; '
                f'$__e = $LASTEXITCODE; '
                f'Write-Output "`n{_CWD_MARKER}$((Get-Location).Path)"; '
                f'exit $__e'
            )
            args = ["powershell", "-NonInteractive", "-Command", wrapped]
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=timeout, cwd=cwd,
            )
        else:
            wrapped = (
                f'{command}\n'
                f'__exit_code=$?\n'
                f'printf "\\n{_CWD_MARKER}%s\\n" "$(pwd)"\n'
                f'exit $__exit_code'
            )
            result = subprocess.run(
                wrapped, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd,
            )

        clean_stdout, new_cwd = _split_cwd_marker(result.stdout or "")
        if new_cwd:
            _set_cwd(new_cwd)

        output = clean_stdout
        if result.stderr:
            output += result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output.strip() or "(no output)"

    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"
