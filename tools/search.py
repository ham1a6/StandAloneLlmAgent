import re
from pathlib import Path
from tools.registry import tool

_MAX_FILES = 50
_MAX_RESULTS = 200


@tool(name="grep", description="正規表現でファイルの内容を検索する")
def grep(pattern: str, path: str = ".", glob: str = "**/*") -> str:
    """
    pattern: 検索する正規表現パターン
    path: 検索のベースディレクトリまたはファイルパス
    glob: ファイルフィルタ（例: **/*.py）
    """
    try:
        base = Path(path)
        regex = re.compile(pattern)
        results: list[str] = []

        targets = [base] if base.is_file() else sorted(base.glob(glob))

        for file_path in targets[:_MAX_FILES]:
            if not file_path.is_file():
                continue
            try:
                lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                for i, line in enumerate(lines, 1):
                    if regex.search(line):
                        rel = file_path.relative_to(base) if base.is_dir() else file_path
                        results.append(f"{rel}:{i}: {line.rstrip()}")
                        if len(results) >= _MAX_RESULTS:
                            break
            except Exception:
                continue
            if len(results) >= _MAX_RESULTS:
                break

        if not results:
            return "(no matches)"
        return "\n".join(results)

    except re.error as e:
        return f"Error: invalid regex: {e}"
    except Exception as e:
        return f"Error: {e}"
