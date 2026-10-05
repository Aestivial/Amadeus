"""Memory tools for Amadeus: remember, recall, and forget.

Enables the agent to persistently retain durable facts about the user,
search across memory files using BM25 relevance ranking, and remove obsolete entries.
"""

from __future__ import annotations

import re
from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from amadeus.memory import Memory
from amadeus.tools.base import ApprovalRequest, Risk, Tool, ToolContext, ToolResult, register

_EXPLICIT_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[a-zA-Z0-9_\-]{16,}", re.IGNORECASE), "API key (sk-...)"),
    (re.compile(r"gh[pousr]_[a-zA-Z0-9]{20,}", re.IGNORECASE), "GitHub token (ghp_...)"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key (AKIA...)"),
    (re.compile(r"(?i)\bpassword\s*[:=]\s*\S+"), "password specification"),
]

_HEX_SECRET = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_BASE64_SECRET = re.compile(r"\b[A-Za-z0-9+/]{32,}={0,2}\b")


def _detect_secret(text: str) -> str | None:
    for pattern, name in _EXPLICIT_SECRET_PATTERNS:
        if pattern.search(text):
            return name

    if _HEX_SECRET.search(text):
        return "hexadecimal secret token (>= 32 chars)"

    for match in _BASE64_SECRET.finditer(text):
        token = match.group(0)
        start = max(0, match.start() - 8)
        prefix = text[start : match.start()]
        if "://" in prefix or prefix.endswith("/"):
            continue
        if any(c.isdigit() for c in token) or "=" in token or "+" in token or "/" in token:
            return "base64/encoded secret token (>= 32 chars)"

    return None


class RememberParams(BaseModel):
    text: str = Field(description="The durable fact to remember about the user.")
    kind: Literal["profile", "preference", "note"] = Field(
        default="note",
        description=(
            "Memory kind: 'profile' (user background/identity), "
            "'preference' (habits/preferences), or 'note' (topical facts)."
        ),
    )
    topic: str | None = Field(
        default=None,
        description=(
            "Topic slug for notes (e.g. 'python', 'general'). "
            "Defaults to 'general' when kind is 'note'."
        ),
    )


@register
class RememberTool(Tool):
    name: ClassVar[str] = "remember"
    description: ClassVar[str] = (
        "Remember durable facts about the user (e.g., name, preferences, dev setup). "
        "Do NOT store secrets, passwords, or API keys. "
        "Use kind='profile' for user identity/role/background, "
        "kind='preference' for habits/coding style/tools, "
        "or kind='note' with an optional topic for project-specific knowledge."
    )
    risk: ClassVar[Risk] = "memory"
    Params: ClassVar[type[BaseModel]] = RememberParams

    def run(self, params: RememberParams, ctx: ToolContext) -> ToolResult:
        secret_kind = _detect_secret(params.text)
        if secret_kind is not None:
            return ToolResult(
                ok=False,
                output=(
                    f"Rejected: text appears to contain a secret ({secret_kind}). "
                    "Never store secrets, passwords, or API keys in memory."
                ),
            )

        untrusted = bool(ctx.extras.get("untrusted_active")) if ctx.extras else False
        req = ApprovalRequest(
            tool=self.name,
            risk=self.risk,
            summary=f"Remember ({params.kind}): {params.text}",
            untrusted_origin=untrusted,
        )
        if not ctx.approve(req):
            return ToolResult(ok=False, output="Denied by user.")

        mem = ctx.extras.get("memory") if ctx.extras else None
        if not isinstance(mem, Memory):
            mem = Memory()

        try:
            status_msg = mem.remember(params.text, kind=params.kind, topic=params.topic)
            return ToolResult(ok=True, output=status_msg)
        except ValueError as e:
            return ToolResult(ok=False, output=str(e))


class RecallParams(BaseModel):
    query: str = Field(description="Search query to locate relevant memories.")
    k: int = Field(default=5, description="Maximum number of memory items to return.")


@register
class RecallTool(Tool):
    name: ClassVar[str] = "recall"
    description: ClassVar[str] = (
        "Search and retrieve memories from the user's profile, preferences, and notes "
        "using BM25 keyword relevance. Returns top matching memories."
    )
    risk: ClassVar[Risk] = "read"
    Params: ClassVar[type[BaseModel]] = RecallParams

    def run(self, params: RecallParams, ctx: ToolContext) -> ToolResult:
        mem = ctx.extras.get("memory") if ctx.extras else None
        if not isinstance(mem, Memory):
            mem = Memory()

        results = mem.recall(query=params.query, k=params.k)
        if not results:
            return ToolResult(ok=True, output="No matching memories found.")
        return ToolResult(ok=True, output="\n".join(results), meta={"count": len(results)})


class ForgetParams(BaseModel):
    text: str = Field(description="Substring to match for removing memory entries.")


@register
class ForgetTool(Tool):
    name: ClassVar[str] = "forget"
    description: ClassVar[str] = (
        "Remove memories matching the specified text (case-insensitive substring) "
        "across profile, preferences, and notes. Use when facts become obsolete."
    )
    risk: ClassVar[Risk] = "memory"
    Params: ClassVar[type[BaseModel]] = ForgetParams

    def run(self, params: ForgetParams, ctx: ToolContext) -> ToolResult:
        untrusted = bool(ctx.extras.get("untrusted_active")) if ctx.extras else False
        req = ApprovalRequest(
            tool=self.name,
            risk=self.risk,
            summary=f"Forget: {params.text}",
            untrusted_origin=untrusted,
        )
        if not ctx.approve(req):
            return ToolResult(ok=False, output="Denied by user.")

        mem = ctx.extras.get("memory") if ctx.extras else None
        if not isinstance(mem, Memory):
            mem = Memory()

        count = mem.forget(params.text)
        unit = "entry" if count == 1 else "entries"
        return ToolResult(ok=True, output=f"Removed {count} memory {unit}.", meta={"count": count})


remember = RememberTool
recall = RecallTool
forget = ForgetTool
