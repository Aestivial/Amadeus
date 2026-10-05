"""Safety policy and command denylist.

Enforces human-in-the-loop approval, mode-based auto-approvals, and a hard
denylist of catastrophic commands across Windows, PowerShell, cmd, and bash.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from amadeus.paths import is_within

if TYPE_CHECKING:
    from amadeus.tools.base import ApprovalRequest

# Precompiled regex patterns for critical targets
RE_CRITICAL_TARGET = re.compile(
    r"""(?:"""
    # Windows drive root: C:, C:\, C:/, C:\*, C:/*, D:, etc.
    r"""["']?[a-zA-Z]:(?:[\\/]+|\*|[\\/]+\*)?["']?(?!\S)"""
    # Standalone root: /, \, /*, \*
    r"""|(?<!\S)["']?[\\/](?:\*)?["']?(?!\S)"""
    # Home directory: ~, ~/, ~\, ~/*, ~\*, "~\*"
    r"""|(?<!\S)["']?~[\\/]?(?:\*)?["']?(?!\S)"""
    # Home / userprofile / system env vars
    r"""|["']?(?:\$HOME|%USERPROFILE%|\$env:USERPROFILE|\$env:HOME|%HOMEPATH%)(?:[\\/]+|\*|[\\/]+\*)?["']?(?!\S)"""
    # Windows system directories
    r"""|["']?(?:[a-zA-Z]:)?[\\/](?:Windows|System32|Program\s+Files(?:\s+\(x86\))?|ProgramData|Users)(?:[\\/]\S*)?["']?"""
    r"""|["']?(?:%windir%|%SystemRoot%|%ProgramFiles%|%ProgramFiles\(x86\)%|\$env:windir|\$env:SystemRoot|\$env:ProgramFiles|\$env:ProgramFiles\(x86\))["']?"""
    # Linux system root directories
    r"""|/(?:etc|usr|bin|sbin|var|boot|lib|lib64|dev|sys|proc|root|home)(?:/\S*)?"""
    r""")""",
    re.IGNORECASE,
)

# Catastrophic command denylist (stand-alone patterns)
DANGEROUS_COMMANDS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"(?i)(?<![\w-])format(?:\.exe)?\s+(?:[a-zA-Z]:|[/-])"),
        "Denied: catastrophic command detected (drive format).",
    ),
    (
        re.compile(r"(?i)(?<![\w-])diskpart(?:\.exe)?\b"),
        "Denied: catastrophic command detected (disk partitioning).",
    ),
    (
        re.compile(r"(?i)(?<![\w-])bcdedit(?:\.exe)?\b"),
        "Denied: catastrophic command detected (boot configuration edit).",
    ),
    (
        re.compile(r"(?i)(?<![\w-])reg(?:\.exe)?\s+delete\s+[\"']?(?:hklm|hkey_local_machine)\b"),
        "Denied: catastrophic command detected (HKLM registry deletion).",
    ),
    (
        re.compile(r"(?i)(?<![\w-])cipher(?:\.exe)?\s+.*?[/-]w\b"),
        "Denied: catastrophic command detected (cipher wipe).",
    ),
    (
        re.compile(r"(?i)(?<![\w-])mkfs(?:\.[a-z0-9]+)?\b"),
        "Denied: catastrophic command detected (filesystem creation).",
    ),
    (
        re.compile(r"(?i)(?<![\w-])dd\b.*?of=/dev/(?:sd|nvme|hd|vd|disk|zero|null|urandom)"),
        "Denied: catastrophic command detected (raw device overwrite via dd).",
    ),
    (
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
        "Denied: catastrophic command detected (bash fork bomb).",
    ),
    (
        re.compile(r"%0\s*\|\s*%0"),
        "Denied: catastrophic command detected (cmd fork bomb).",
    ),
    (
        re.compile(r"(?i)(?<![\w-])Stop-Computer\b"),
        "Denied: catastrophic command detected (system shutdown).",
    ),
    (
        re.compile(r"(?i)(?<![\w-])shutdown(?:\.exe)?\s+(?:.*?\s+)?[/-][sr]\b"),
        "Denied: catastrophic command detected (system shutdown/reboot).",
    ),
    (
        re.compile(r"(?i)(?<![\w-])vssadmin(?:\.exe)?\s+delete\s+shadows\b"),
        "Denied: catastrophic command detected (shadow copy deletion).",
    ),
    (
        re.compile(
            r"(?i)(?<![\w-])takeown(?:\.exe)?\b.*?(?:[a-zA-Z]:[\\/]+(?:Windows|System32|Program\s+Files)|/(?:etc|usr|bin|sbin|boot|lib)|%windir%|%systemroot%|\$env:windir|\$env:systemroot)"
        ),
        "Denied: catastrophic command detected (takeown on system directory).",
    ),
]

RE_CMD_SPLIT = re.compile(r"[;&|\n]")


def denied_reason(command: str) -> str | None:
    """Hard denylist check. Returns denial reason if catastrophic, else None."""
    cmd = command.strip()
    if not cmd:
        return None

    # Check stand-alone dangerous commands across the full command
    for pattern, reason in DANGEROUS_COMMANDS:
        if pattern.search(cmd):
            return reason

    # Check recursive deletions per command segment
    segments = RE_CMD_SPLIT.split(cmd)
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        # PowerShell / bash rm / Remove-Item / rmi
        is_rm = bool(re.search(r"(?i)(?<![\w-])(?:rm|Remove-Item|rmi)\b", seg))
        if is_rm:
            has_rec = bool(
                re.search(
                    r"(?i)(?<![\w-])(?:-[a-z0-9]*r[a-z0-9]*|-recurse\b|--recursive\b)",
                    seg,
                )
            )
            if has_rec and RE_CRITICAL_TARGET.search(seg):
                return "Denied: catastrophic command detected (recursive delete of critical path)."

        # cmd rd / rmdir
        is_rd = bool(re.search(r"(?i)(?<![\w-])(?:rd|rmdir)\b", seg))
        if is_rd:
            has_rec = bool(re.search(r"(?i)(?<![\w-])[/-]s\b", seg))
            if has_rec and RE_CRITICAL_TARGET.search(seg):
                return "Denied: catastrophic command detected (recursive delete of critical path)."

        # cmd del / erase
        is_del = bool(re.search(r"(?i)(?<![\w-])(?:del|erase)\b", seg))
        if is_del:
            has_rec = bool(re.search(r"(?i)(?<![\w-])[/-]s\b", seg))
            if has_rec and RE_CRITICAL_TARGET.search(seg):
                return "Denied: catastrophic command detected (recursive delete of critical path)."

    return None


class Policy:
    """Security policy managing tool approvals and session grants."""

    def __init__(
        self,
        mode: str,
        workspace: Path,
        prompt: Callable[[ApprovalRequest], str] | None = None,
    ) -> None:
        self.mode = mode
        self.workspace = Path(workspace).resolve()
        self._prompt = prompt
        self._always_allowed: set[tuple[str, str]] = set()

    def approve(self, req: ApprovalRequest) -> bool:
        """Evaluate approval for a tool request."""
        # read is always permitted without asking
        if req.risk == "read":
            return True

        # Check session "always" grants (keyed by (tool, risk))
        # Untrusted origin always requires explicit confirmation
        if not req.untrusted_origin and (req.tool, req.risk) in self._always_allowed:
            return True

        needs_prompt = False

        if req.risk == "memory":
            if req.untrusted_origin:
                needs_prompt = True
            elif self.mode == "yolo":
                return True
            else:
                needs_prompt = True

        elif req.risk == "write":
            if self.mode in ("auto", "yolo") and not req.untrusted_origin:
                if req.path is not None:
                    target = (
                        (self.workspace / req.path).resolve()
                        if not Path(req.path).is_absolute()
                        else Path(req.path).resolve()
                    )
                    if is_within(target, self.workspace):
                        return True
                    else:
                        needs_prompt = True
                else:
                    needs_prompt = True
            else:
                needs_prompt = True

        elif req.risk in ("exec", "net"):
            if self.mode == "yolo" and not req.untrusted_origin:
                return True
            else:
                needs_prompt = True

        else:
            needs_prompt = True

        if not needs_prompt:
            return True

        # Prompt for confirmation
        prompt_fn = self._prompt
        if prompt_fn is None:
            from amadeus.ui import confirm

            prompt_fn = confirm

        ans = prompt_fn(req)
        if isinstance(ans, str):
            ans = ans.strip().lower()

        if ans == "a":
            self._always_allowed.add((req.tool, req.risk))
            return True

        return ans in ("y", "yes", True)
