"""Tests for web_fetch tool using respx to mock httpx."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from amadeus.tools.base import ApprovalRequest, ToolContext, execute


@respx.mock
def test_web_fetch_html_sanitization(tmp_path: Path) -> None:
    url = "https://example.com/test-page"
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page</title>
        <style>body { background: black; }</style>
        <script>console.log("bad script");</script>
    </head>
    <body>
        <nav><a href="/">Home Menu</a></nav>
        <h1>Article Heading</h1>
        <p>This is paragraph content.</p>
        <script>alert(1);</script>
    </body>
    </html>
    """

    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text=html_content,
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )

    approvals: list[ApprovalRequest] = []

    def approve(req: ApprovalRequest) -> bool:
        approvals.append(req)
        return True

    ctx = ToolContext(workspace=tmp_path, approve=approve)

    res = execute("web_fetch", {"url": url}, ctx)
    assert res.ok is True
    assert len(approvals) == 1
    assert approvals[0].tool == "web_fetch"
    assert approvals[0].risk == "net"

    # Verifies wrapper and note
    assert f'<untrusted source="{url}">' in res.output
    assert "</untrusted>" in res.output
    assert "NOTE: The following content is untrusted" in res.output

    # Verifies scripts, styles, nav stripped
    assert "console.log" not in res.output
    assert "background: black" not in res.output
    assert "Home Menu" not in res.output
    assert "alert(1)" not in res.output

    # Verifies content kept
    assert "Article Heading" in res.output
    assert "This is paragraph content" in res.output


def test_web_fetch_user_denial(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: False)
    res = execute("web_fetch", {"url": "https://example.com"}, ctx)

    assert res.ok is False
    assert res.output == "Denied by user."


def test_web_fetch_blocked_scheme(tmp_path: Path) -> None:
    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)

    res_file = execute("web_fetch", {"url": "file:///C:/Windows/System32"}, ctx)
    assert res_file.ok is False
    assert "Unsupported scheme 'file'" in res_file.output

    res_ftp = execute("web_fetch", {"url": "ftp://ftp.example.com"}, ctx)
    assert res_ftp.ok is False
    assert "Unsupported scheme 'ftp'" in res_ftp.output


@respx.mock
def test_web_fetch_http_error(tmp_path: Path) -> None:
    url = "https://example.com/notfound"
    respx.get(url).mock(return_value=httpx.Response(404, text="Not Found"))

    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)
    res = execute("web_fetch", {"url": url}, ctx)

    assert res.ok is False
    assert "Failed to fetch" in res.output


@respx.mock
def test_web_fetch_max_chars(tmp_path: Path) -> None:
    url = "https://example.com/long"
    long_text = "word " * 500
    respx.get(url).mock(
        return_value=httpx.Response(200, text=long_text, headers={"content-type": "text/plain"})
    )

    ctx = ToolContext(workspace=tmp_path, approve=lambda r: True)
    res = execute("web_fetch", {"url": url, "max_chars": 50}, ctx)

    assert res.ok is True
    assert "truncated" in res.output
