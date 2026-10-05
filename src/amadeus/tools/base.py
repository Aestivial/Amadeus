"""Tool base classes and registry. Every tool subclasses `Tool` and is
registered with the `@register` decorator.

Approval flow: tools that write/exec/fetch call `ctx.approve(ApprovalRequest)`
*themselves* (they know the best detail to show: a diff, the command, the URL).
If it returns False the tool must return ToolResult(ok=False, output="Denied by user.").
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel

Risk = Literal["read", "write", "exec", "net", "memory"]


@dataclass
class ApprovalRequest:
    tool: str
    risk: Risk
    summary: str  # one line, e.g. "Run: git status" / "Write src/x.py"
    detail: str = ""  # diff, full command, URL ...
    path: Path | None = None  # target path for write ops (outside-workspace checks)
    untrusted_origin: bool = False  # triggered while processing web/file content


@dataclass
class ToolResult:
    ok: bool
    output: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolContext:
    workspace: Path
    approve: Callable[[ApprovalRequest], bool]
    max_output_chars: int = 12_000
    shell_timeout: int = 120
    extras: dict[str, Any] = field(default_factory=dict)  # e.g. {"memory": Memory}


class Tool:
    name: ClassVar[str]
    description: ClassVar[str]
    risk: ClassVar[Risk]
    Params: ClassVar[type[BaseModel]]

    def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:  # pragma: no cover
        raise NotImplementedError

    @classmethod
    def schema(cls) -> dict[str, Any]:
        """OpenAI-compatible function schema."""
        params = cls.Params.model_json_schema()
        params.pop("title", None)
        return {
            "type": "function",
            "function": {"name": cls.name, "description": cls.description, "parameters": params},
        }


REGISTRY: dict[str, type[Tool]] = {}


def register(cls: type[Tool]) -> type[Tool]:
    REGISTRY[cls.name] = cls
    return cls


def openai_tools(names: list[str] | None = None) -> list[dict[str, Any]]:
    return [t.schema() for n, t in REGISTRY.items() if names is None or n in names]


def execute(name: str, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Validate arguments and run a tool. Never raises; errors become ToolResult(ok=False)."""
    cls = REGISTRY.get(name)
    if cls is None:
        return ToolResult(False, f"Unknown tool '{name}'. Available: {', '.join(REGISTRY)}")
    try:
        params = cls.Params.model_validate(arguments or {})
    except Exception as e:  # pydantic.ValidationError
        return ToolResult(False, f"Invalid arguments for {name}: {e}")
    try:
        return cls().run(params, ctx)
    except Exception as e:
        return ToolResult(False, f"{name} failed: {type(e).__name__}: {e}")
