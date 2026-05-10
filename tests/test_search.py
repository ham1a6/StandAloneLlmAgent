import pytest
from pathlib import Path
import tools.search
from tools.search import grep


def test_grep_finds_match(tmp_path):
    (tmp_path / "code.py").write_text("def foo():\n    return 42\n", encoding="utf-8")
    result = grep("def foo", str(tmp_path))
    assert "code.py" in result
    assert "def foo" in result


def test_grep_no_match(tmp_path):
    (tmp_path / "code.py").write_text("def bar():\n    pass\n", encoding="utf-8")
    result = grep("def foo", str(tmp_path))
    assert "no matches" in result


def test_grep_on_single_file(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("hello world\ngoodbye world\n", encoding="utf-8")
    result = grep("hello", str(f))
    assert "hello world" in result
    assert "goodbye" not in result


def test_grep_reports_line_numbers(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("a\nb\nhello\nd\n", encoding="utf-8")
    result = grep("hello", str(tmp_path))
    assert ":3:" in result


def test_grep_invalid_regex(tmp_path):
    result = grep("[invalid", str(tmp_path))
    assert "Error" in result


def test_grep_glob_filter(tmp_path):
    (tmp_path / "a.py").write_text("import foo\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("import foo\n", encoding="utf-8")
    result = grep("import foo", str(tmp_path), glob="*.py")
    assert "a.py" in result
    assert "b.txt" not in result


def test_grep_multiple_files(tmp_path):
    (tmp_path / "x.py").write_text("TODO: fix this\n", encoding="utf-8")
    (tmp_path / "y.py").write_text("TODO: and this\n", encoding="utf-8")
    result = grep("TODO", str(tmp_path))
    assert "x.py" in result
    assert "y.py" in result
