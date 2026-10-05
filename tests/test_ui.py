"""Tests for UI components, banner rendering, approval confirmation, and personas."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from amadeus import __version__, paths
from amadeus.tools.base import ApprovalRequest
from amadeus.ui import (
    confirm,
    error,
    info,
    print_banner,
    render_markdown,
    show_diff,
    spinner,
    stream_printer,
    warn,
)


def test_print_banner_with_assets(monkeypatch) -> None:
    test_console = Console(record=True, width=100)
    monkeypatch.setattr("amadeus.ui.console", test_console)

    print_banner(compact=False)
    output = test_console.export_text()

    assert f"v{__version__}" in output
    assert "AMADEUS" in output
    assert "local agent system" in output


def test_print_banner_compact(monkeypatch) -> None:
    test_console = Console(record=True, width=100)
    monkeypatch.setattr("amadeus.ui.console", test_console)

    print_banner(compact=True)
    output = test_console.export_text()

    assert f"v{__version__}" in output
    assert "AMADEUS" in output


def test_print_banner_narrow_terminal(monkeypatch) -> None:
    test_console = Console(record=True, width=60)
    monkeypatch.setattr("amadeus.ui.console", test_console)

    print_banner(compact=False)
    output = test_console.export_text()

    assert f"v{__version__}" in output
    assert "AMADEUS" in output


def test_print_banner_missing_assets(monkeypatch, tmp_path: Path) -> None:
    test_console = Console(record=True, width=80)
    monkeypatch.setattr("amadeus.ui.console", test_console)
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))

    print_banner(compact=False)
    output = test_console.export_text()

    assert "AMADEUS" in output
    assert f"v{__version__}" in output


def test_confirm_mapped_values(monkeypatch) -> None:
    test_console = Console(record=True)
    monkeypatch.setattr("amadeus.ui.console", test_console)

    req = ApprovalRequest(
        tool="shell",
        risk="exec",
        summary="Run: ls",
        detail="Get-ChildItem",
        untrusted_origin=False,
    )

    test_cases = [
        ("y", "y"),
        ("yes", "y"),
        ("YES", "y"),
        ("n", "n"),
        ("no", "n"),
        ("a", "a"),
        ("always", "a"),
        ("ALWAYS", "a"),
        ("other", "n"),
    ]

    for user_input, expected in test_cases:
        monkeypatch.setattr(Prompt, "ask", lambda *args, inp=user_input, **kwargs: inp)
        result = confirm(req)
        assert result == expected, f"Input {user_input!r} expected {expected!r}, got {result!r}"


def test_confirm_keyboard_interrupt(monkeypatch) -> None:
    test_console = Console(record=True)
    monkeypatch.setattr("amadeus.ui.console", test_console)

    req = ApprovalRequest(
        tool="shell",
        risk="exec",
        summary="Run dangerous command",
    )

    def raise_interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(Prompt, "ask", raise_interrupt)
    assert confirm(req) == "n"


def test_confirm_rendering_details(monkeypatch) -> None:
    test_console = Console(record=True)
    monkeypatch.setattr("amadeus.ui.console", test_console)
    monkeypatch.setattr(Prompt, "ask", lambda *args, **kwargs: "n")

    # Test diff detail and untrusted origin warning
    req_diff = ApprovalRequest(
        tool="file_write",
        risk="write",
        summary="Write file foo.py",
        detail="--- a/foo.py\n+++ b/foo.py\n-old\n+new",
        path=Path("foo.py"),
        untrusted_origin=True,
    )
    confirm(req_diff)
    output = test_console.export_text()

    assert "file_write" in output
    assert "WRITE" in output
    assert "foo.py" in output
    assert "Untrusted origin" in output


def test_show_diff(monkeypatch) -> None:
    test_console = Console(record=True)
    monkeypatch.setattr("amadeus.ui.console", test_console)

    show_diff("line1\nline2\n", "line1\nline_modified\n", "example.py")
    output = test_console.export_text()

    assert "Diff: example.py" in output
    assert "-line2" in output
    assert "+line_modified" in output


def test_show_diff_no_changes(monkeypatch) -> None:
    test_console = Console(record=True)
    monkeypatch.setattr("amadeus.ui.console", test_console)

    show_diff("same", "same", "example.py")
    output = test_console.export_text()

    assert "Diff: example.py" in output
    assert "(no changes)" in output


def test_render_markdown(monkeypatch) -> None:
    test_console = Console(record=True)
    monkeypatch.setattr("amadeus.ui.console", test_console)

    render_markdown("# Title Heading\n\n```python\nprint('hello')\n```")
    output = test_console.export_text()

    assert "Title Heading" in output
    assert "hello" in output


def test_spinner(monkeypatch) -> None:
    test_console = Console(record=True)
    monkeypatch.setattr("amadeus.ui.console", test_console)

    with spinner("Processing task"):
        pass


def test_info_warn_error(monkeypatch) -> None:
    test_console = Console(record=True)
    monkeypatch.setattr("amadeus.ui.console", test_console)

    info("Informational message [bracketed]")
    warn("Warning message")
    error("Critical failure")

    output = test_console.export_text()
    assert "Informational message [bracketed]" in output
    assert "Warning message" in output
    assert "Critical failure" in output


def test_stream_printer(monkeypatch) -> None:
    test_console = Console(record=True)
    printer = stream_printer(test_console)

    printer.write("token_one")
    printer.write(" ")
    printer.write("token_two")
    printer.end()

    output = test_console.export_text()
    assert "token_one token_two" in output


def test_persona_files_exist_and_bounded() -> None:
    persona_dir = paths.persona_dir()

    amadeus_file = persona_dir / "amadeus.md"
    plain_file = persona_dir / "plain.md"

    assert amadeus_file.is_file(), f"Missing {amadeus_file}"
    assert plain_file.is_file(), f"Missing {plain_file}"

    amadeus_content = amadeus_file.read_text(encoding="utf-8")
    plain_content = plain_file.read_text(encoding="utf-8")

    assert len(amadeus_content) < 4000, f"amadeus.md exceeds 4000 chars ({len(amadeus_content)})"
    assert len(plain_content) < 4000, f"plain.md exceeds 4000 chars ({len(plain_content)})"

    # Check key persona traits in amadeus.md
    assert "Amadeus" in amadeus_content
    assert "neuroscience" in amadeus_content
    assert "El Psy Kongroo" in amadeus_content
    assert "Dr Pepper" in amadeus_content
    assert "Competence First" in amadeus_content

    # Check work rules in plain.md
    assert "Amadeus" in plain_content
    assert "Empirical Verification" in plain_content
    assert "Zero Fabrication" in plain_content
