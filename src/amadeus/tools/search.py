"""Search tools: glob and grep."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel

from amadeus.tools.base import Risk, Tool, ToolContext, ToolResult, register
from amadeus.tools.files import IGNORED_DIRS, is_binary_file, read_text_and_newline, resolve_path


class GlobParams(BaseModel):
    pattern: str
    path: str = "."


@register
class GlobTool(Tool):
    name: ClassVar[str] = "glob"
    description: ClassVar[str] = "Find files matching a glob pattern."
    risk: ClassVar[Risk] = "read"
    Params: ClassVar[type[BaseModel]] = GlobParams

    def run(self, params: GlobParams, ctx: ToolContext) -> ToolResult:
        target = resolve_path(ctx, params.path)
        if not target.exists():
            return ToolResult(ok=False, output=f"Directory not found: {params.path}")
        if not target.is_dir():
            return ToolResult(ok=False, output=f"Path is not a directory: {params.path}")

        matches: list[str] = []
        try:
            for p in target.glob(params.pattern):
                if any(part in IGNORED_DIRS for part in p.parts):
                    continue
                try:
                    rel = p.relative_to(ctx.workspace)
                except ValueError:
                    rel = p
                matches.append(str(rel).replace("\\", "/"))
        except Exception as e:
            return ToolResult(ok=False, output=f"Glob error: {e}")

        matches.sort()
        if not matches:
            return ToolResult(ok=True, output="No matching files found.")
        return ToolResult(ok=True, output="\n".join(matches))


class GrepParams(BaseModel):
    pattern: str
    path: str = "."
    glob: str | None = None
    case_insensitive: bool = False
    max_results: int = 100


def _pure_python_grep(
    workspace: Path,
    target: Path,
    pattern: str,
    glob_filter: str | None,
    case_insensitive: bool,
    max_results: int,
) -> list[str]:
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        raise ValueError(f"Invalid regex: {e}") from e

    results: list[str] = []

    def search_file(file_path: Path) -> None:
        if is_binary_file(file_path):
            return
        try:
            text, _ = read_text_and_newline(file_path)
        except Exception:
            return

        try:
            rel_path = file_path.relative_to(workspace)
        except ValueError:
            rel_path = file_path
        rel_str = str(rel_path).replace("\\", "/")

        for line_idx, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                results.append(f"{rel_str}:{line_idx}: {line}")
                if len(results) >= max_results:
                    return

    if target.is_file():
        search_file(target)
        return results

    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for file in sorted(files):
            if glob_filter and not fnmatch.fnmatch(file, glob_filter):
                continue
            file_path = Path(root) / file
            search_file(file_path)
            if len(results) >= max_results:
                return results

    return results


@register
class GrepTool(Tool):
    name: ClassVar[str] = "grep"
    description: ClassVar[str] = "Search for regex patterns in files."
    risk: ClassVar[Risk] = "read"
    Params: ClassVar[type[BaseModel]] = GrepParams

    def run(self, params: GrepParams, ctx: ToolContext) -> ToolResult:
        target = resolve_path(ctx, params.path)
        if not target.exists():
            return ToolResult(ok=False, output=f"Path not found: {params.path}")

        # Check if ripgrep is available on PATH
        rg_path = shutil.which("rg")
        if rg_path:
            cmd = [
                rg_path,
                "-n",
                "--color",
                "never",
                "--no-heading",
            ]
            if params.case_insensitive:
                cmd.append("-i")
            if params.glob:
                cmd.extend(["-g", params.glob])
            for d in IGNORED_DIRS:
                cmd.extend(["-g", f"!{d}/**"])
            cmd.extend(["-m", str(params.max_results)])
            cmd.extend(["-e", params.pattern])

            try:
                rel_target = target.relative_to(ctx.workspace)
                target_arg = str(rel_target) if str(rel_target) != "." else "."
            except ValueError:
                target_arg = str(target)
            cmd.append(target_arg)

            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(ctx.workspace),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
            except Exception:
                proc = None

            if proc is not None:
                if proc.returncode == 0:
                    lines = [
                        re.sub(r"^([^:]+)", lambda m: m.group(1).replace("\\", "/"), line)
                        for line in proc.stdout.splitlines()
                        if line.strip()
                    ]
                    if lines:
                        return ToolResult(ok=True, output="\n".join(lines[: params.max_results]))
                    return ToolResult(ok=True, output="No matches found.")
                elif proc.returncode == 1:
                    return ToolResult(ok=True, output="No matches found.")
                else:
                    # On ripgrep error, fallback to pure python search
                    pass

        # Pure-Python fallback
        try:
            results = _pure_python_grep(
                workspace=ctx.workspace,
                target=target,
                pattern=params.pattern,
                glob_filter=params.glob,
                case_insensitive=params.case_insensitive,
                max_results=params.max_results,
            )
        except ValueError as e:
            return ToolResult(ok=False, output=str(e))
        except Exception as e:
            return ToolResult(ok=False, output=f"Search failed: {e}")

        if not results:
            return ToolResult(ok=True, output="No matches found.")

        return ToolResult(ok=True, output="\n".join(results[: params.max_results]))
