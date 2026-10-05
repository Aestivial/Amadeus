"""Tests for safety policy and catastrophic command denylist."""

from __future__ import annotations

from pathlib import Path

import pytest

from amadeus.safety import Policy, denied_reason
from amadeus.tools.base import ApprovalRequest


@pytest.mark.parametrize(
    "cmd",
    [
        "Remove-Item -Recurse -Force C:\\",
        "Remove-Item -Recurse C:\\*",
        "Remove-Item -Recurse ~",
        "Remove-Item -Recurse $env:USERPROFILE",
        'Remove-Item -Recurse -Force "C:\\Windows"',
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf $HOME",
        'rm -rf "/etc"',
        "rd /s /q C:\\",
        'rd /s /q "C:\\"',
        "del /s /q C:\\*",
        'del /s /q "C:\\*"',
        "format c:",
        "format D: /fs:ntfs",
        "diskpart",
        "diskpart /s script.txt",
        "bcdedit",
        "bcdedit /delete {default}",
        "reg delete HKLM",
        'reg delete "HKLM\\Software\\Test" /f',
        "cipher /w:C",
        "cipher /w",
        "mkfs /dev/sda1",
        "mkfs.ext4 /dev/sdb1",
        "dd if=/dev/zero of=/dev/sda",
        ":(){ :|:& };:",
        "%0|%0",
        "Stop-Computer",
        "Stop-Computer -Force",
        "shutdown /s /t 0",
        "shutdown /r /t 0",
        "shutdown -s",
        "shutdown -r",
        "vssadmin delete shadows",
        "vssadmin delete shadows /all /quiet",
        "takeown /f C:\\Windows",
        "takeown /f C:\\Windows\\System32 /r",
    ],
)
def test_denied_reason_blocks_catastrophic_commands(cmd: str) -> None:
    reason = denied_reason(cmd)
    assert reason is not None
    assert "Denied" in reason


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf build",
        "rm -rf ./build",
        "Remove-Item .\\dist -Recurse",
        "Remove-Item -Recurse .\\temp",
        "git clean -n",
        "git clean -fdx",
        "format-table",
        "Format-List",
        "format-table -AutoSize",
        "python script.py",
        "echo hi",
        "git status",
        "ls -la",
        "dir",
    ],
)
def test_denied_reason_allows_safe_commands(cmd: str) -> None:
    assert denied_reason(cmd) is None


def test_policy_ask_mode(tmp_path: Path) -> None:
    prompt_history: list[ApprovalRequest] = []

    def mock_prompt(req: ApprovalRequest) -> str:
        prompt_history.append(req)
        return "y"

    policy = Policy(mode="ask", workspace=tmp_path, prompt=mock_prompt)

    # Read is always auto-approved
    assert policy.approve(ApprovalRequest(tool="read_file", risk="read", summary="Read file"))
    assert len(prompt_history) == 0

    # Write inside workspace prompts in 'ask' mode
    inside_file = tmp_path / "foo.txt"
    assert policy.approve(
        ApprovalRequest(tool="write_file", risk="write", summary="Write file", path=inside_file)
    )
    assert len(prompt_history) == 1

    # Exec prompts
    assert policy.approve(ApprovalRequest(tool="shell", risk="exec", summary="Run shell"))
    assert len(prompt_history) == 2

    # Net prompts
    assert policy.approve(ApprovalRequest(tool="web_fetch", risk="net", summary="Fetch url"))
    assert len(prompt_history) == 3


def test_policy_auto_mode(tmp_path: Path) -> None:
    prompt_calls: list[ApprovalRequest] = []

    def mock_prompt(req: ApprovalRequest) -> str:
        prompt_calls.append(req)
        return "y"

    policy = Policy(mode="auto", workspace=tmp_path, prompt=mock_prompt)

    # Read approved without prompt
    assert policy.approve(ApprovalRequest(tool="read_file", risk="read", summary="read"))
    assert len(prompt_calls) == 0

    # Write inside workspace approved without prompt
    inside = tmp_path / "src" / "a.py"
    assert policy.approve(
        ApprovalRequest(tool="write_file", risk="write", summary="write", path=inside)
    )
    assert len(prompt_calls) == 0

    # Write outside workspace prompts
    outside = tmp_path.parent / "outside.py"
    assert policy.approve(
        ApprovalRequest(tool="write_file", risk="write", summary="write", path=outside)
    )
    assert len(prompt_calls) == 1

    # Exec and net prompt in auto mode
    assert policy.approve(ApprovalRequest(tool="shell", risk="exec", summary="exec"))
    assert len(prompt_calls) == 2
    assert policy.approve(ApprovalRequest(tool="web_fetch", risk="net", summary="net"))
    assert len(prompt_calls) == 3


def test_policy_yolo_mode(tmp_path: Path) -> None:
    prompt_calls: list[ApprovalRequest] = []

    def mock_prompt(req: ApprovalRequest) -> str:
        prompt_calls.append(req)
        return "y"

    policy = Policy(mode="yolo", workspace=tmp_path, prompt=mock_prompt)

    # Everything inside workspace approved without prompt
    assert policy.approve(ApprovalRequest(tool="read_file", risk="read", summary="read"))
    assert policy.approve(
        ApprovalRequest(tool="write_file", risk="write", summary="write", path=tmp_path / "test.py")
    )
    assert policy.approve(ApprovalRequest(tool="shell", risk="exec", summary="exec"))
    assert policy.approve(ApprovalRequest(tool="web_fetch", risk="net", summary="net"))
    assert policy.approve(ApprovalRequest(tool="remember", risk="memory", summary="remember"))
    assert len(prompt_calls) == 0

    # Write outside workspace still prompts
    outside = tmp_path.parent / "outside.py"
    assert policy.approve(
        ApprovalRequest(tool="write_file", risk="write", summary="write", path=outside)
    )
    assert len(prompt_calls) == 1

    # Memory with untrusted_origin still prompts in yolo mode
    assert policy.approve(
        ApprovalRequest(
            tool="remember",
            risk="memory",
            summary="remember untrusted",
            untrusted_origin=True,
        )
    )
    assert len(prompt_calls) == 2


def test_policy_session_always_grant(tmp_path: Path) -> None:
    prompt_count = 0

    def mock_prompt(req: ApprovalRequest) -> str:
        nonlocal prompt_count
        prompt_count += 1
        return "a"

    policy = Policy(mode="ask", workspace=tmp_path, prompt=mock_prompt)

    req1 = ApprovalRequest(tool="shell", risk="exec", summary="Run 1")
    assert policy.approve(req1)
    assert prompt_count == 1

    # Second call for the same (tool, risk) does not prompt
    req2 = ApprovalRequest(tool="shell", risk="exec", summary="Run 2")
    assert policy.approve(req2)
    assert prompt_count == 1

    # Different tool still prompts
    req3 = ApprovalRequest(tool="web_fetch", risk="net", summary="Fetch")
    assert policy.approve(req3)
    assert prompt_count == 2

    # Untrusted origin still prompts despite session grant
    req_untrusted = ApprovalRequest(
        tool="shell", risk="exec", summary="Untrusted", untrusted_origin=True
    )
    assert policy.approve(req_untrusted)
    assert prompt_count == 3


def test_policy_rejection(tmp_path: Path) -> None:
    policy = Policy(mode="ask", workspace=tmp_path, prompt=lambda r: "n")
    assert not policy.approve(ApprovalRequest(tool="shell", risk="exec", summary="Run"))
