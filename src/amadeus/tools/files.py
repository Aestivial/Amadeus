"""Filesystem tools: read, write, edit files and list directories."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from amadeus.tools.base import ApprovalRequest, Risk, Tool, ToolContext, ToolResult, register
from amadeus.util import truncate_middle

IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".runtime"}


def resolve_path(ctx: ToolContext, path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p.resolve()
    return (ctx.workspace / p).resolve()


def is_binary_file(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except Exception:
        return False


def read_text_and_newline(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return text, newline


def write_text_preserving_newline(path: Path, content: str, default_newline: str = "\n") -> None:
    newline = default_newline
    if path.exists():
        try:
            with open(path, "rb") as f:
                raw = f.read(2048)
                if b"\r\n" in raw:
                    newline = "\r\n"
                elif b"\n" in raw:
                    newline = "\n"
        except Exception:
            pass

    normalized = content.replace("\r\n", "\n")
    if newline == "\r\n":
        final_text = normalized.replace("\n", "\r\n")
    else:
        final_text = normalized
    path.write_bytes(final_text.encode("utf-8"))


def format_size(size: int) -> str:
    sz = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if sz < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(sz)} B"
            return f"{sz:.1f} {unit}"
        sz /= 1024
    return f"{int(sz)} B"


class ReadFileParams(BaseModel):
    path: str
    start_line: int | None = None
    end_line: int | None = None


@register
class ReadFileTool(Tool):
    name: ClassVar[str] = "read_file"
    description: ClassVar[str] = "Read file content with line numbers."
    risk: ClassVar[Risk] = "read"
    Params: ClassVar[type[BaseModel]] = ReadFileParams

    def run(self, params: ReadFileParams, ctx: ToolContext) -> ToolResult:
        target = resolve_path(ctx, params.path)
        if not target.exists():
            return ToolResult(ok=False, output=f"File not found: {params.path}")
        if target.is_dir():
            return ToolResult(ok=False, output=f"Path is a directory: {params.path}")
        if is_binary_file(target):
            return ToolResult(ok=False, output=f"Cannot read binary file: {params.path}")

        try:
            text, _ = read_text_and_newline(target)
        except Exception as e:
            return ToolResult(ok=False, output=f"Failed to read file: {e}")

        lines = text.splitlines()
        total = len(lines)
        if total == 0:
            return ToolResult(ok=True, output="(empty file)")

        start = 1 if params.start_line is None else max(1, params.start_line)
        end = total if params.end_line is None else min(total, params.end_line)

        if start > total:
            return ToolResult(
                ok=True,
                output=(
                    f"(File has {total} lines; start_line {params.start_line} exceeds file length)"
                ),
            )

        formatted_lines = [f"{idx:6d} | {lines[idx - 1]}" for idx in range(start, end + 1)]
        out = "\n".join(formatted_lines)
        truncated = truncate_middle(out, ctx.max_output_chars)
        return ToolResult(ok=True, output=truncated)


class WriteFileParams(BaseModel):
    path: str
    content: str


@register
class WriteFileTool(Tool):
    name: ClassVar[str] = "write_file"
    description: ClassVar[str] = "Write or overwrite a file in the workspace."
    risk: ClassVar[Risk] = "write"
    Params: ClassVar[type[BaseModel]] = WriteFileParams

    def run(self, params: WriteFileParams, ctx: ToolContext) -> ToolResult:
        target = resolve_path(ctx, params.path)

        if target.exists() and not target.is_dir():
            old_text, _ = read_text_and_newline(target)
            diff = "".join(
                difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    params.content.splitlines(keepends=True),
                    fromfile=f"a/{params.path}",
                    tofile=f"b/{params.path}",
                )
            )
            detail = diff if diff else "(no changes)"
        else:
            detail = f"New file ({len(params.content)} chars):\n" + truncate_middle(
                params.content, 2000
            )

        req = ApprovalRequest(
            tool="write_file",
            risk="write",
            summary=f"Write {params.path}",
            detail=detail,
            path=target,
        )
        if not ctx.approve(req):
            return ToolResult(ok=False, output="Denied by user.")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text_preserving_newline(target, params.content)
        except Exception as e:
            return ToolResult(ok=False, output=f"Failed to write file: {e}")

        return ToolResult(
            ok=True, output=f"Wrote {len(params.content)} characters to {params.path}"
        )


class EditFileParams(BaseModel):
    path: str
    old_text: str
    new_text: str
    replace_all: bool = False


@register
class EditFileTool(Tool):
    name: ClassVar[str] = "edit_file"
    description: ClassVar[str] = "Replace text in an existing file."
    risk: ClassVar[Risk] = "write"
    Params: ClassVar[type[BaseModel]] = EditFileParams

    def run(self, params: EditFileParams, ctx: ToolContext) -> ToolResult:
        target = resolve_path(ctx, params.path)
        if not target.exists():
            return ToolResult(ok=False, output=f"File not found: {params.path}")
        if target.is_dir():
            return ToolResult(ok=False, output=f"Path is a directory: {params.path}")
        if is_binary_file(target):
            return ToolResult(ok=False, output=f"Cannot edit binary file: {params.path}")

        try:
            content, newline = read_text_and_newline(target)
        except Exception as e:
            return ToolResult(ok=False, output=f"Failed to read file: {e}")

        norm_content = content.replace("\r\n", "\n")
        norm_old = params.old_text.replace("\r\n", "\n")
        norm_new = params.new_text.replace("\r\n", "\n")

        count = norm_content.count(norm_old)
        if count == 0:
            file_lines = norm_content.splitlines()
            old_lines = [line.strip() for line in norm_old.splitlines() if line.strip()]
            hint = ""
            for oline in old_lines[:3]:
                matches = difflib.get_close_matches(oline, file_lines, n=1, cutoff=0.5)
                if matches:
                    hint = f" (closest matching line: '{matches[0]}')"
                    break
            return ToolResult(
                ok=False,
                output=f"old_text not found in {params.path}.{hint}",
            )

        if count > 1 and not params.replace_all:
            return ToolResult(
                ok=False,
                output=(
                    f"old_text found {count} times in {params.path}. "
                    "Set replace_all=True or provide more surrounding context."
                ),
            )

        if params.replace_all:
            new_content = norm_content.replace(norm_old, norm_new)
        else:
            new_content = norm_content.replace(norm_old, norm_new, 1)

        diff = "".join(
            difflib.unified_diff(
                norm_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{params.path}",
                tofile=f"b/{params.path}",
            )
        )

        req = ApprovalRequest(
            tool="edit_file",
            risk="write",
            summary=f"Edit {params.path}",
            detail=diff,
            path=target,
        )
        if not ctx.approve(req):
            return ToolResult(ok=False, output="Denied by user.")

        try:
            write_text_preserving_newline(target, new_content, default_newline=newline)
        except Exception as e:
            return ToolResult(ok=False, output=f"Failed to edit file: {e}")

        return ToolResult(ok=True, output=f"Successfully edited {params.path}")


class ListDirParams(BaseModel):
    path: str = "."
    depth: int = Field(default=1, ge=1, le=3)


@register
class ListDirTool(Tool):
    name: ClassVar[str] = "list_dir"
    description: ClassVar[str] = "List directory contents up to depth 3."
    risk: ClassVar[Risk] = "read"
    Params: ClassVar[type[BaseModel]] = ListDirParams

    def run(self, params: ListDirParams, ctx: ToolContext) -> ToolResult:
        target = resolve_path(ctx, params.path)
        if not target.exists():
            return ToolResult(ok=False, output=f"Directory not found: {params.path}")
        if not target.is_dir():
            return ToolResult(ok=False, output=f"Path is not a directory: {params.path}")

        max_depth = min(max(params.depth, 1), 3)
        entries: list[str] = []
        capped = False

        def walk(dir_path: Path, current_depth: int) -> None:
            nonlocal capped
            if capped or current_depth > max_depth:
                return
            try:
                items = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except PermissionError:
                return

            for item in items:
                if item.name in IGNORED_DIRS:
                    continue
                if len(entries) >= 500:
                    capped = True
                    return

                try:
                    rel = item.relative_to(target)
                except ValueError:
                    rel = item

                rel_str = str(rel).replace("\\", "/")
                if item.is_dir():
                    entries.append(f"[DIR]  {rel_str}/")
                    if current_depth < max_depth:
                        walk(item, current_depth + 1)
                else:
                    try:
                        sz = item.stat().st_size
                        sz_str = format_size(sz)
                    except Exception:
                        sz_str = "? B"
                    entries.append(f"[FILE] {rel_str} ({sz_str})")

        walk(target, 1)

        if not entries:
            out = f"Directory {params.path} is empty."
        else:
            out = "\n".join(entries)
            if capped:
                out += "\n... [capped at 500 entries]"

        return ToolResult(ok=True, output=out)
