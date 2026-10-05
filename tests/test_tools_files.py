"""Tests for filesystem tools: read_file, write_file, edit_file, list_dir."""

from __future__ import annotations

from pathlib import Path

from amadeus.tools.base import ApprovalRequest, ToolContext, execute


def test_read_file_normal_and_slice(tmp_path: Path) -> None:
    f = tmp_path / "sample.txt"
    f.write_text("line 1\nline 2\nline 3\nline 4\n", encoding="utf-8")

    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)

    # Full read
    res = execute("read_file", {"path": "sample.txt"}, ctx)
    assert res.ok is True
    assert "1 | line 1" in res.output
    assert "4 | line 4" in res.output

    # Sliced read
    res_slice = execute("read_file", {"path": "sample.txt", "start_line": 2, "end_line": 3}, ctx)
    assert res_slice.ok is True
    assert "2 | line 2" in res_slice.output
    assert "3 | line 3" in res_slice.output
    assert "1 | line 1" not in res_slice.output
    assert "4 | line 4" not in res_slice.output


def test_read_file_binary_and_missing(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)

    # Non-existent file
    res_missing = execute("read_file", {"path": "missing.txt"}, ctx)
    assert res_missing.ok is False
    assert "File not found" in res_missing.output

    # Binary file
    bin_file = tmp_path / "data.bin"
    bin_file.write_bytes(b"\x00\x01\x02\x03\x04")
    res_bin = execute("read_file", {"path": "data.bin"}, ctx)
    assert res_bin.ok is False
    assert "Cannot read binary file" in res_bin.output


def test_write_file_new_and_overwrite(tmp_path: Path) -> None:
    approvals: list[ApprovalRequest] = []

    def approve(req: ApprovalRequest) -> bool:
        approvals.append(req)
        return True

    ctx = ToolContext(workspace=tmp_path, approve=approve)

    # New file in nested directory
    res_new = execute(
        "write_file", {"path": "nested/dir/hello.txt", "content": "Hello World\n"}, ctx
    )
    assert res_new.ok is True
    assert (tmp_path / "nested/dir/hello.txt").read_text(encoding="utf-8") == "Hello World\n"
    assert len(approvals) == 1
    assert "New file" in approvals[0].detail
    assert approvals[0].path == (tmp_path / "nested/dir/hello.txt").resolve()

    # Overwrite file generates diff
    res_overwrite = execute(
        "write_file",
        {"path": "nested/dir/hello.txt", "content": "Hello Universe\n"},
        ctx,
    )
    assert res_overwrite.ok is True
    assert (tmp_path / "nested/dir/hello.txt").read_text(encoding="utf-8") == "Hello Universe\n"
    assert len(approvals) == 2
    assert "---" in approvals[1].detail
    assert "+++" in approvals[1].detail


def test_write_file_denial(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: False)
    res = execute("write_file", {"path": "test.txt", "content": "abc"}, ctx)
    assert res.ok is False
    assert res.output == "Denied by user."
    assert not (tmp_path / "test.txt").exists()


def test_edit_file_success_and_diff(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")

    approvals: list[ApprovalRequest] = []

    def approve(req: ApprovalRequest) -> bool:
        approvals.append(req)
        return True

    ctx = ToolContext(workspace=tmp_path, approve=approve)

    res = execute(
        "edit_file",
        {"path": "code.py", "old_text": "return 1", "new_text": "return 2"},
        ctx,
    )
    assert res.ok is True
    assert f.read_text(encoding="utf-8") == "def foo():\n    return 2\n"
    assert len(approvals) == 1
    assert "-    return 1" in approvals[0].detail
    assert "+    return 2" in approvals[0].detail


def test_edit_file_not_found_with_hint(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("def my_special_function():\n    pass\n", encoding="utf-8")

    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)

    res = execute(
        "edit_file",
        {"path": "code.py", "old_text": "def my_special_func():", "new_text": "pass"},
        ctx,
    )
    assert res.ok is False
    assert "old_text not found" in res.output
    assert "closest matching line" in res.output or "my_special_function" in res.output


def test_edit_file_multiple_occurrences(tmp_path: Path) -> None:
    f = tmp_path / "text.txt"
    f.write_text("item\nitem\nitem\n", encoding="utf-8")

    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)

    # Without replace_all should fail
    res_fail = execute(
        "edit_file",
        {"path": "text.txt", "old_text": "item", "new_text": "element"},
        ctx,
    )
    assert res_fail.ok is False
    assert "found 3 times" in res_fail.output

    # With replace_all should succeed
    res_ok = execute(
        "edit_file",
        {
            "path": "text.txt",
            "old_text": "item",
            "new_text": "element",
            "replace_all": True,
        },
        ctx,
    )
    assert res_ok.ok is True
    assert f.read_text(encoding="utf-8") == "element\nelement\nelement\n"


def test_list_dir(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)

    (tmp_path / "file1.txt").write_text("hello", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "file2.txt").write_text("world!", encoding="utf-8")

    # Ignored directories
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git config", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.json").write_text("{}", encoding="utf-8")

    # Depth 1
    res_d1 = execute("list_dir", {"path": ".", "depth": 1}, ctx)
    assert res_d1.ok is True
    assert "file1.txt" in res_d1.output
    assert "[DIR]  sub/" in res_d1.output
    assert "file2.txt" not in res_d1.output
    assert ".git" not in res_d1.output
    assert "node_modules" not in res_d1.output

    # Depth 2
    res_d2 = execute("list_dir", {"path": ".", "depth": 2}, ctx)
    assert res_d2.ok is True
    assert "file1.txt" in res_d2.output
    assert "file2.txt" in res_d2.output
    assert ".git" not in res_d2.output
