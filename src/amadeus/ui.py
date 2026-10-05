"""UI components and formatting for Amadeus terminal interface."""

from __future__ import annotations

import difflib
import os
from typing import TYPE_CHECKING, Literal

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.text import Text

from amadeus import __version__, paths

if TYPE_CHECKING:
    from rich.status import Status

    from amadeus.tools.base import ApprovalRequest

console: Console = Console()

RISK_COLORS: dict[str, str] = {
    "read": "green",
    "write": "yellow",
    "exec": "red",
    "net": "magenta",
    "memory": "cyan",
}

MAP_CHOICE: dict[str, Literal["y", "n", "a"]] = {
    "y": "y",
    "yes": "y",
    "n": "n",
    "no": "n",
    "a": "a",
    "always": "a",
}


def print_banner(compact: bool = False) -> None:
    """Print the Amadeus logo in a crimson gradient with version subtitle."""
    banner_dir = paths.assets_dir()
    use_small = compact or (console.width < 70)
    primary_name = "banner_small.txt" if use_small else "banner.txt"
    secondary_name = "banner.txt" if use_small else "banner_small.txt"

    primary_path = banner_dir / primary_name
    secondary_path = banner_dir / secondary_name

    content: str | None = None
    if primary_path.is_file():
        try:
            content = primary_path.read_text(encoding="utf-8")
        except OSError:
            content = None
    elif secondary_path.is_file():
        try:
            content = secondary_path.read_text(encoding="utf-8")
        except OSError:
            content = None

    if content and content.strip():
        lines = content.splitlines()
        n = len(lines)
        for i, line in enumerate(lines):
            t = i / max(1, n - 1)
            r = int(255 + (139 - 255) * t)
            g = int(42 + (0 - 42) * t)
            b = int(77 + (0 - 77) * t)
            color = f"#{r:02x}{g:02x}{b:02x}"
            console.print(Text(line, style=color))
    else:
        # Fallback gracefully if assets missing
        console.print(Text("AMADEUS", style="bold #ff2a4d"))

    console.print(Text(f"AMADEUS  ·  v{__version__}  ·  local agent system", style="dim"))


def render_markdown(text: str) -> None:
    """Render markdown using the Monokai code theme."""
    from rich.markdown import Markdown

    console.print(Markdown(text, code_theme="monokai"))


def show_diff(old: str, new: str, path: str) -> None:
    """Display a unified diff with green/red syntax highlighting inside a Panel."""
    diff_lines = list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    diff_text = "".join(diff_lines) if diff_lines else "(no changes)\n"
    syntax = Syntax(diff_text, "diff", theme="monokai", word_wrap=True)
    panel = Panel(syntax, title=f"Diff: {path}", border_style="yellow")
    console.print(panel)


def confirm(req: ApprovalRequest) -> Literal["y", "n", "a"]:
    """Display tool approval details in a risk-colored Panel and prompt the user."""
    risk_color = RISK_COLORS.get(req.risk, "white")
    elements: list[RenderableType] = []

    header = Text.assemble(
        ("Tool: ", "bold"),
        (req.tool, "bold bright_white"),
        ("  |  Risk: ", "bold"),
        (req.risk.upper(), f"bold {risk_color}"),
    )
    elements.append(header)

    if req.path is not None:
        elements.append(Text(f"Path: {req.path}", style="italic"))

    elements.append(Text(f"Summary: {req.summary}"))

    if req.untrusted_origin:
        elements.append(
            Text(
                "WARNING: Untrusted origin - triggered from external content!",
                style="bold red",
            )
        )

    if req.detail:
        detail_str = req.detail.strip()
        is_diff = (
            detail_str.startswith("---")
            or detail_str.startswith("diff ")
            or "\n@@ " in req.detail
            or detail_str.startswith("@@ ")
        )
        if is_diff:
            lexer = "diff"
        elif req.risk == "exec":
            lexer = "powershell" if os.name == "nt" else "bash"
        else:
            lexer = None

        if lexer:
            elements.append(Syntax(req.detail, lexer, theme="monokai", word_wrap=True))
        else:
            elements.append(Text(req.detail))

    panel = Panel(
        Group(*elements),
        title=f"[{risk_color}]Approval Request[/{risk_color}]",
        border_style=risk_color,
    )
    console.print(panel)

    try:
        ans = Prompt.ask(
            "Allow? [y]es / [n]o / [a]lways this session",
            choices=["y", "n", "a"],
            default="n",
            console=console,
        )
        ans_str = str(ans).strip().lower()
        return MAP_CHOICE.get(ans_str, "n")
    except (KeyboardInterrupt, EOFError):
        console.print()
        return "n"


def spinner(text: str) -> Status:
    """Context manager displaying a crimson 'dots' spinner."""
    return console.status(text, spinner="dots", spinner_style="#ff2a4d")


def info(msg: object) -> None:
    """Display an info message."""
    text = Text.assemble(("INFO  ", "bold cyan"), (str(msg), ""))
    console.print(text)


def warn(msg: object) -> None:
    """Display a warning message."""
    text = Text.assemble(("WARN  ", "bold yellow"), (str(msg), ""))
    console.print(text)


def error(msg: object) -> None:
    """Display an error message."""
    text = Text.assemble(("ERROR ", "bold red"), (str(msg), ""))
    console.print(text)


class StreamPrinter:
    """Helper to stream LLM tokens immediately to the console without markup/highlighting."""

    def __init__(self, c: Console | None = None) -> None:
        self._console = c or console
        self._has_written = False

    def write(self, text: str) -> None:
        if text:
            self._has_written = True
            self._console.print(text, end="", markup=False, highlight=False)

    def end(self) -> None:
        if self._has_written:
            self._console.print()
            self._has_written = False


def stream_printer(c: Console | None = None) -> StreamPrinter:
    """Create a new stream printer."""
    return StreamPrinter(c)
