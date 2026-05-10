from pathlib import Path
from tools.registry import tool


@tool(name="read_file", description="ファイルを読み込む（行番号付き）")
def read_file(path: str, offset: int = 0, limit: int = 200) -> str:
    """
    path: 読み込むファイルのパス
    offset: 開始行（0始まり）
    limit: 読み込む最大行数
    """
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: file not found: {path}"
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(lines)
        sliced = lines[offset: offset + limit]
        result = "\n".join(f"{offset + i + 1}\t{line}" for i, line in enumerate(sliced))
        if total > offset + limit:
            result += f"\n... ({total - offset - limit} more lines)"
        return result
    except Exception as e:
        return f"Error: {e}"


@tool(name="write_file", description="ファイルを新規作成または上書きする")
def write_file(path: str, content: str) -> str:
    """
    path: 書き込むファイルのパス
    content: ファイルの内容
    """
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"Error: {e}"


@tool(name="edit_file", description="ファイル内の文字列を一箇所だけ置換する")
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """
    path: 編集するファイルのパス
    old_string: 置換前の文字列（ファイル内で一意である必要がある）
    new_string: 置換後の文字列
    """
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: file not found: {path}"
        content = p.read_text(encoding="utf-8")
        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {path}"
        if count > 1:
            return f"Error: old_string matches {count} times — must be unique"
        p.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


@tool(name="list_dir", description="ディレクトリの内容を一覧表示する")
def list_dir(path: str = ".") -> str:
    """path: 一覧表示するディレクトリのパス"""
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: not found: {path}"
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = []
        for entry in entries:
            if entry.is_dir():
                lines.append(f"[dir]  {entry.name}/")
            else:
                lines.append(f"[file] {entry.name}  ({entry.stat().st_size} bytes)")
        return "\n".join(lines) if lines else "(empty)"
    except Exception as e:
        return f"Error: {e}"


@tool(name="glob", description="glob パターンでファイルを検索する")
def glob_files(pattern: str, path: str = ".") -> str:
    """
    pattern: glob パターン（例: **/*.py）
    path: 検索のベースディレクトリ
    """
    try:
        base = Path(path)
        matches = sorted(base.glob(pattern))
        if not matches:
            return "(no matches)"
        return "\n".join(str(m.relative_to(base)) for m in matches[:100])
    except Exception as e:
        return f"Error: {e}"
