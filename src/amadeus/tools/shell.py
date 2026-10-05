"""Shell execution tool for Amadeus."""

from __future__ import annotations

import os
import subprocess
from typing import ClassVar

from pydantic import BaseModel

from amadeus.safety import denied_reason
from amadeus.tools.base import ApprovalRequest, Risk, Tool, ToolContext, ToolResult, register
from amadeus.util import truncate_middle


class ShellParams(BaseModel):
    command: str
    cwd: str | None = None
    timeout: int | None = None


@register
class ShellTool(Tool):
    name: ClassVar[str] = "shell"
    description: ClassVar[str] = "Run a shell command in the workspace."
    risk: ClassVar[Risk] = "exec"
    Params: ClassVar[type[BaseModel]] = ShellParams

    def run(self, params: ShellParams, ctx: ToolContext) -> ToolResult:
        # Check hard denylist first without asking for approval
        reason = denied_reason(params.command)
        if reason:
            return ToolResult(ok=False, output=reason)

        # Request user approval
        req = ApprovalRequest(
            tool="shell",
            risk="exec",
            summary=f"Run: {params.command}",
            detail=params.command,
        )
        if not ctx.approve(req):
            return ToolResult(ok=False, output="Denied by user.")

        # Resolve working directory relative to workspace
        if params.cwd:
            work_dir = (ctx.workspace / params.cwd).resolve()
        else:
            work_dir = ctx.workspace.resolve()

        if not work_dir.is_dir():
            return ToolResult(ok=False, output=f"Working directory does not exist: {params.cwd}")

        timeout = (
            params.timeout
            if params.timeout is not None and params.timeout > 0
            else ctx.shell_timeout
        )

        if os.name == "nt":
            ps_cmd = f"[Console]::OutputEncoding=[Text.Encoding]::UTF8; {params.command}"
            cmd_list = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_cmd,
            ]
        else:
            cmd_list = ["bash", "-lc", params.command]

        try:
            proc = subprocess.Popen(
                cmd_list,
                cwd=str(work_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except Exception as e:
            return ToolResult(ok=False, output=f"Failed to start command: {e}")

        timed_out = False
        try:
            stdout_bytes, _ = proc.communicate(timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                proc.kill()
            stdout_bytes, _ = proc.communicate()
            exit_code = -1

        decoded = (stdout_bytes or b"").decode("utf-8", errors="replace").replace("\r\n", "\n")

        if timed_out:
            output_text = f"exit code: {exit_code} (timed out after {timeout}s)\n{decoded}".strip()
        else:
            if decoded:
                output_text = f"exit code: {exit_code}\n{decoded}".rstrip()
            else:
                output_text = f"exit code: {exit_code}"

        truncated = truncate_middle(output_text, ctx.max_output_chars)
        return ToolResult(
            ok=(exit_code == 0 and not timed_out),
            output=truncated,
            meta={"exit_code": exit_code, "timed_out": timed_out},
        )
