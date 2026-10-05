"""Tests for search tools: glob and grep."""

from __future__ import annotations

from pathlib import Path

import pytest

from amadeus.tools.base import ToolContext, execute


def test_glob_tool(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)

    (tmp_path / "a.py").write_text("print('a')", encoding="utf-8")
    (tmp_path / "b.txt").write_text("text b", encoding="utf-8")
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "c.py").write_text("print('c')", encoding="utf-8")

    # Ignored directory
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "ignore.py").write_text("ignore", encoding="utf-8")

    res_py = execute("glob", {"pattern": "**/*.py"}, ctx)
    assert res_py.ok is True
    assert "a.py" in res_py.output
    assert "pkg/c.py" in res_py.output
    assert "ignore.py" not in res_py.output
    assert "b.txt" not in res_py.output

    res_none = execute("glob", {"pattern": "*.cpp"}, ctx)
    assert res_none.ok is True
    assert "No matching files found" in res_none.output


def test_grep_tool_pure_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force pure-python fallback by hiding rg
    monkeypatch.setattr("shutil.which", lambda cmd: None)

    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)

    (tmp_path / "file1.py").write_text(
        "import sys\n# Target pattern here\nprint('done')\n", encoding="utf-8"
    )
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "file2.txt").write_text("first line\ntarget pattern here\nlast line\n", encoding="utf-8")

    # Binary file (should be skipped)
    bin_file = tmp_path / "binary.dat"
    bin_file.write_bytes(b"\x00Target pattern here\x00")

    # Ignored dir (should be skipped)
    node_dir = tmp_path / "node_modules"
    node_dir.mkdir()
    (node_dir / "lib.js").write_text("Target pattern here", encoding="utf-8")

    # Case-sensitive search
    res = execute("grep", {"pattern": "Target pattern", "path": "."}, ctx)
    assert res.ok is True
    assert "file1.py:2: # Target pattern here" in res.output
    assert "sub/file2.txt:2: target pattern here" not in res.output
    assert "binary.dat" not in res.output
    assert "node_modules" not in res.output

    # Case-insensitive search
    res_i = execute(
        "grep",
        {"pattern": "target pattern", "path": ".", "case_insensitive": True},
        ctx,
    )
    assert res_i.ok is True
    assert "file1.py:2: # Target pattern here" in res_i.output
    assert "sub/file2.txt:2: target pattern here" in res_i.output

    # Glob filter
    res_glob = execute(
        "grep",
        {
            "pattern": "target pattern",
            "path": ".",
            "glob": "*.py",
            "case_insensitive": True,
        },
        ctx,
    )
    assert res_glob.ok is True
    assert "file1.py:2: # Target pattern here" in res_glob.output
    assert "sub/file2.txt" not in res_glob.output


def test_grep_tool_max_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)

    lines = "\n".join(f"match line {i}" for i in range(20))
    (tmp_path / "many.txt").write_text(lines, encoding="utf-8")

    res = execute("grep", {"pattern": "match line", "max_results": 5}, ctx)
    assert res.ok is True
    out_lines = [line for line in res.output.splitlines() if line.strip()]
    assert len(out_lines) == 5


def test_grep_no_matches(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)
    (tmp_path / "test.txt").write_text("nothing special", encoding="utf-8")

    res = execute("grep", {"pattern": "nonexistent_pattern_xyz"}, ctx)
    assert res.ok is True
    assert "No matches found" in res.output
