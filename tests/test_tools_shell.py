"""Tests for shell tool."""

from __future__ import annotations

import os
from pathlib import Path

from amadeus.tools.base import ApprovalRequest, ToolContext, execute


def test_shell_simple_command(tmp_path: Path) -> None:
    approvals: list[ApprovalRequest] = []

    def approve(req: ApprovalRequest) -> bool:
        approvals.append(req)
        return True

    ctx = ToolContext(workspace=tmp_path, approve=approve)
    cmd = "Write-Output hello_amadeus" if os.name == "nt" else "echo hello_amadeus"
    res = execute("shell", {"command": cmd}, ctx)

    assert res.ok is True
    assert "exit code: 0" in res.output
    assert "hello_amadeus" in res.output
    assert len(approvals) == 1
    assert approvals[0].tool == "shell"
    assert approvals[0].risk == "exec"


def test_shell_nonzero_exit(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)
    cmd = "exit 42"
    res = execute("shell", {"command": cmd}, ctx)

    assert res.ok is False
    assert "exit code: 42" in res.output


def test_shell_timeout(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True, shell_timeout=1)
    cmd = "Start-Sleep -Seconds 5" if os.name == "nt" else "sleep 5"
    res = execute("shell", {"command": cmd, "timeout": 1}, ctx)

    assert res.ok is False
    assert "timed out" in res.output


def test_shell_denied_command(tmp_path: Path) -> None:
    asked = False

    def approve(req: ApprovalRequest) -> bool:
        nonlocal asked
        asked = True
        return True

    ctx = ToolContext(workspace=tmp_path, approve=approve)
    res = execute("shell", {"command": "Remove-Item -Recurse -Force C:\\"}, ctx)

    assert res.ok is False
    assert "Denied: catastrophic command detected" in res.output
    # Denied commands must NEVER prompt for approval
    assert not asked


def test_shell_user_denial(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: False)
    cmd = "Write-Output hi" if os.name == "nt" else "echo hi"
    res = execute("shell", {"command": cmd}, ctx)

    assert res.ok is False
    assert res.output == "Denied by user."


def test_shell_cwd(tmp_path: Path) -> None:
    subdir = tmp_path / "sub"
    subdir.mkdir()
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)

    cmd = "[Console]::WriteLine((Get-Location).Path)" if os.name == "nt" else "pwd"
    res = execute("shell", {"command": cmd, "cwd": "sub"}, ctx)

    assert res.ok is True
    assert "sub" in res.output


def test_shell_cwd_nonexistent(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)
    cmd = "echo hi"
    res = execute("shell", {"command": cmd, "cwd": "nonexistent_dir"}, ctx)

    assert res.ok is False
    assert "Working directory does not exist" in res.output
