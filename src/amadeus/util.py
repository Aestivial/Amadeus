"""Small shared helpers."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token). Good enough for budgeting."""
    return max(1, len(text) // 4) if text else 0


def truncate_middle(
    text: str, max_chars: int, marker: str = "\n... [{n} chars truncated] ...\n"
) -> str:
    """Keep head and tail of long text (errors usually live at the end)."""
    if len(text) <= max_chars:
        return text
    keep = max(0, max_chars - 60)
    head = keep * 2 // 3
    tail = keep - head
    cut = len(text) - head - tail
    return text[:head] + marker.format(n=cut) + (text[-tail:] if tail else "")
