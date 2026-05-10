import platform
import subprocess
import os
from tools.registry import tool

_IS_WINDOWS = platform.system() == "Windows"


@tool(name="bash", description="シェルコマンドを実行する（Windows は PowerShell、Unix は bash）")
def bash(command: str, timeout: int = 60) -> str:
    """
    command: 実行するシェルコマンド
    timeout: タイムアウト秒数
    """
    try:
        if _IS_WINDOWS:
            # PowerShell では quoted パスから始まるコマンドに & 演算子が必要
            cmd = command.strip()
            if cmd.startswith('"') or cmd.startswith("'"):
                cmd = f"& {cmd}"
            args = ["powershell", "-NonInteractive", "-Command", cmd]
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.getcwd(),
            )
        else:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.getcwd(),
            )

        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output.strip() or "(no output)"

    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"
