from __future__ import annotations

from pathlib import Path

import pytest

from amadeus.memory import Memory
from amadeus.tools.base import REGISTRY, ApprovalRequest, ToolContext, execute
from amadeus.tools.memory_tools import (
    ForgetParams,
    ForgetTool,
    RecallParams,
    RecallTool,
    RememberParams,
    RememberTool,
)


@pytest.fixture
def mock_context(tmp_path: Path) -> tuple[ToolContext, list[ApprovalRequest]]:
    approvals: list[ApprovalRequest] = []

    def approve(req: ApprovalRequest) -> bool:
        approvals.append(req)
        return True

    ctx = ToolContext(
        workspace=tmp_path,
        approve=approve,
        extras={"memory": Memory(directory=tmp_path)},
    )
    return ctx, approvals


def test_remember_tool_normal_flow(mock_context: tuple[ToolContext, list[ApprovalRequest]]) -> None:
    ctx, approvals = mock_context
    tool = RememberTool()
    params = RememberParams(text="Alice is a data engineer", kind="profile")

    result = tool.run(params, ctx)
    assert result.ok is True
    assert "Remembered (profile): Alice is a data engineer" in result.output

    # Check approval request
    assert len(approvals) == 1
    req = approvals[0]
    assert req.tool == "remember"
    assert req.risk == "memory"
    assert req.summary == "Remember (profile): Alice is a data engineer"
    assert req.untrusted_origin is False

    # Check persisted memory
    mem: Memory = ctx.extras["memory"]
    recall_res = mem.recall("data engineer")
    assert len(recall_res) == 1
    assert "Alice is a data engineer" in recall_res[0]


def test_secret_rejection(mock_context: tuple[ToolContext, list[ApprovalRequest]]) -> None:
    ctx, approvals = mock_context
    tool = RememberTool()

    secret_samples = [
        ("sk-ant-api03-abcdef1234567890abcdef1234567890", "sk-..."),
        ("ghp_1234567890abcdef1234567890abcdef1234", "ghp_..."),
        ("AKIAIOSFODNN7EXAMPLE", "AKIA..."),
        ("My password is password: secretpassword123", "password: ..."),
        ("Password=MySuperSecretPass!123", "password="),
        ("Hex token is 4f8b2d1e6a9c3f5e0b7a8d9c2e1f4a6b", "32 hex"),
        (
            "Base64 secret is SGVsbG8gV29ybGQgdGhpcyBpcyBhIHRlc3QgdG9rZW4gZm9yIHRlc3Rpbmc=",
            "base64 token",
        ),
    ]

    for secret_text, label in secret_samples:
        params = RememberParams(text=secret_text, kind="note", topic="secrets")
        result = tool.run(params, ctx)

        assert result.ok is False, f"Failed to reject secret: {label}"
        assert "Rejected:" in result.output
        assert "secret" in result.output.lower()

    # Crucial: verify approval was NEVER requested for secrets!
    assert len(approvals) == 0

    # Verify nothing was added to memory
    mem: Memory = ctx.extras["memory"]
    assert mem.recall("secret") == []


def test_approval_denied_path(tmp_path: Path) -> None:
    ctx = ToolContext(
        workspace=tmp_path,
        approve=lambda req: False,  # Denies all requests
        extras={"memory": Memory(directory=tmp_path)},
    )

    # Remember denied
    rem_tool = RememberTool()
    rem_res = rem_tool.run(
        RememberParams(text="Sensitive preference", kind="preference"),
        ctx,
    )
    assert rem_res.ok is False
    assert rem_res.output == "Denied by user."

    # Forget denied
    forget_tool = ForgetTool()
    forget_res = forget_tool.run(
        ForgetParams(text="Sensitive preference"),
        ctx,
    )
    assert forget_res.ok is False
    assert forget_res.output == "Denied by user."


def test_untrusted_flag_propagated(tmp_path: Path) -> None:
    captured: list[ApprovalRequest] = []

    def approve(req: ApprovalRequest) -> bool:
        captured.append(req)
        return True

    # When untrusted_active is True
    ctx_untrusted = ToolContext(
        workspace=tmp_path,
        approve=approve,
        extras={"memory": Memory(directory=tmp_path), "untrusted_active": True},
    )

    rem_tool = RememberTool()
    rem_tool.run(RememberParams(text="Fact from untrusted web page", kind="note"), ctx_untrusted)

    assert len(captured) == 1
    assert captured[0].untrusted_origin is True

    forget_tool = ForgetTool()
    forget_tool.run(ForgetParams(text="Fact"), ctx_untrusted)

    assert len(captured) == 2
    assert captured[1].untrusted_origin is True

    # When untrusted_active is False
    captured.clear()
    ctx_trusted = ToolContext(
        workspace=tmp_path,
        approve=approve,
        extras={"memory": Memory(directory=tmp_path), "untrusted_active": False},
    )
    rem_tool.run(RememberParams(text="Trusted fact", kind="note"), ctx_trusted)
    assert len(captured) == 1
    assert captured[0].untrusted_origin is False


def test_recall_tool(mock_context: tuple[ToolContext, list[ApprovalRequest]]) -> None:
    ctx, _ = mock_context
    mem: Memory = ctx.extras["memory"]
    mem.remember("Prefers TypeScript for web development", kind="preference")

    recall_tool = RecallTool()
    res = recall_tool.run(RecallParams(query="typescript", k=5), ctx)
    assert res.ok is True
    assert "[preferences] Prefers TypeScript for web development" in res.output

    # No match
    empty_res = recall_tool.run(RecallParams(query="haskell", k=5), ctx)
    assert empty_res.ok is True
    assert empty_res.output == "No matching memories found."


def test_forget_tool(mock_context: tuple[ToolContext, list[ApprovalRequest]]) -> None:
    ctx, approvals = mock_context
    mem: Memory = ctx.extras["memory"]
    mem.remember("Loves Java 8", kind="preference")
    mem.remember("Legacy Java projects", kind="note", topic="work")

    forget_tool = ForgetTool()
    res = forget_tool.run(ForgetParams(text="java"), ctx)
    assert res.ok is True
    assert "Removed 2 memory entries." in res.output

    # Approval was invoked
    assert any(a.tool == "forget" and a.summary == "Forget: java" for a in approvals)

    # Memories actually gone
    assert mem.recall("java") == []


def test_tools_registered_and_execute_helper(tmp_path: Path) -> None:
    assert "remember" in REGISTRY
    assert "recall" in REGISTRY
    assert "forget" in REGISTRY

    ctx = ToolContext(
        workspace=tmp_path,
        approve=lambda req: True,
        extras={"memory": Memory(directory=tmp_path)},
    )

    # Execute remember
    res1 = execute("remember", {"text": "Alice speaks French", "kind": "profile"}, ctx)
    assert res1.ok is True
    assert "Remembered (profile):" in res1.output

    # Execute recall
    res2 = execute("recall", {"query": "french"}, ctx)
    assert res2.ok is True
    assert "Alice speaks French" in res2.output

    # Execute forget
    res3 = execute("forget", {"text": "french"}, ctx)
    assert res3.ok is True
    assert "Removed 1 memory entry." in res3.output


def test_fallback_memory_when_not_in_extras(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))
    ctx = ToolContext(
        workspace=tmp_path,
        approve=lambda req: True,
        extras={},  # No memory provided in extras
    )

    rem_tool = RememberTool()
    res = rem_tool.run(RememberParams(text="Default fallback memory", kind="profile"), ctx)
    assert res.ok is True

    recall_tool = RecallTool()
    recall_res = recall_tool.run(RecallParams(query="fallback"), ctx)
    assert recall_res.ok is True
    assert "Default fallback memory" in recall_res.output
