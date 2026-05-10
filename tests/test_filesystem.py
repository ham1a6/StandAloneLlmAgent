import pytest
from pathlib import Path
import tools.filesystem
from tools.filesystem import read_file, write_file, edit_file, list_dir, glob_files


def test_read_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("line1\nline2\nline3", encoding="utf-8")
    result = read_file(str(f))
    assert "1\tline1" in result
    assert "2\tline2" in result
    assert "3\tline3" in result


def test_read_file_not_found(tmp_path):
    result = read_file(str(tmp_path / "missing.txt"))
    assert "Error" in result


def test_read_file_offset(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("\n".join(str(i) for i in range(10)), encoding="utf-8")
    result = read_file(str(f), offset=5, limit=3)
    assert "6\t5" in result
    assert "8\t7" in result
    assert "1\t0" not in result


def test_read_file_truncation_notice(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("\n".join(["x"] * 300), encoding="utf-8")
    result = read_file(str(f), limit=200)
    assert "more lines" in result


def test_write_file_creates_and_reads_back(tmp_path):
    path = str(tmp_path / "out.txt")
    result = write_file(path, "hello world")
    assert "Written" in result
    assert Path(path).read_text(encoding="utf-8") == "hello world"


def test_write_file_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "a" / "b" / "c.txt")
    write_file(path, "nested")
    assert Path(path).exists()


def test_write_file_overwrites(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("old", encoding="utf-8")
    write_file(str(f), "new")
    assert f.read_text(encoding="utf-8") == "new"


def test_edit_file_success(tmp_path):
    f = tmp_path / "edit.txt"
    f.write_text("hello world", encoding="utf-8")
    result = edit_file(str(f), "hello", "goodbye")
    assert "Edited" in result
    assert f.read_text(encoding="utf-8") == "goodbye world"


def test_edit_file_not_found(tmp_path):
    result = edit_file(str(tmp_path / "missing.txt"), "x", "y")
    assert "Error" in result


def test_edit_file_old_string_not_found(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("hello", encoding="utf-8")
    result = edit_file(str(f), "world", "earth")
    assert "not found" in result


def test_edit_file_multiple_matches(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("abc abc", encoding="utf-8")
    result = edit_file(str(f), "abc", "xyz")
    assert "2 times" in result
    assert f.read_text(encoding="utf-8") == "abc abc"  # unchanged


def test_list_dir_shows_files_and_dirs(tmp_path):
    (tmp_path / "subdir").mkdir()
    (tmp_path / "file.py").write_text("x", encoding="utf-8")
    result = list_dir(str(tmp_path))
    assert "subdir/" in result
    assert "file.py" in result


def test_list_dir_not_found(tmp_path):
    result = list_dir(str(tmp_path / "missing"))
    assert "Error" in result


def test_list_dir_empty(tmp_path):
    result = list_dir(str(tmp_path))
    assert result == "(empty)"


def test_glob_matches_pattern(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")
    result = glob_files("*.py", str(tmp_path))
    assert "a.py" in result
    assert "b.py" in result
    assert "c.txt" not in result


def test_glob_no_matches(tmp_path):
    result = glob_files("*.rs", str(tmp_path))
    assert "no matches" in result


def test_glob_recursive(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text("x", encoding="utf-8")
    result = glob_files("**/*.py", str(tmp_path))
    assert "deep.py" in result
