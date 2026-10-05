from __future__ import annotations

from pathlib import Path

import pytest

from amadeus import paths, util
from amadeus.memory import Memory


def test_remember_creates_files_and_headers(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)

    r_prof = mem.remember("Name is Alice", kind="profile")
    assert r_prof == "Remembered (profile): Name is Alice"

    r_pref = mem.remember("Prefers dark mode", kind="preference")
    assert r_pref == "Remembered (preference): Prefers dark mode"

    r_note = mem.remember("Uses FastAPI for backend", kind="note", topic="python")
    assert r_note == "Remembered (note): Uses FastAPI for backend"

    r_gen = mem.remember("General thought", kind="note")
    assert r_gen == "Remembered (note): General thought"

    assert (tmp_path / "profile.md").is_file()
    assert (tmp_path / "preferences.md").is_file()
    assert (tmp_path / "notes" / "python.md").is_file()
    assert (tmp_path / "notes" / "general.md").is_file()

    prof_text = (tmp_path / "profile.md").read_text(encoding="utf-8")
    assert prof_text.startswith("# Profile\n")
    assert "- Name is Alice  <!-- " in prof_text

    pref_text = (tmp_path / "preferences.md").read_text(encoding="utf-8")
    assert pref_text.startswith("# Preferences\n")
    assert "- Prefers dark mode  <!-- " in pref_text

    note_text = (tmp_path / "notes" / "python.md").read_text(encoding="utf-8")
    assert note_text.startswith("# Notes: python\n")
    assert "- Uses FastAPI for backend  <!-- " in note_text


def test_remember_whitespace_normalisation(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)
    res = mem.remember("   Alice    is   a \n software  engineer. \t  ", kind="profile")
    assert res == "Remembered (profile): Alice is a software engineer."

    prof_text = (tmp_path / "profile.md").read_text(encoding="utf-8")
    assert "- Alice is a software engineer.  <!-- " in prof_text


def test_remember_rejects_empty_and_too_long(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)

    with pytest.raises(ValueError, match="cannot be empty"):
        mem.remember("")

    with pytest.raises(ValueError, match="cannot be empty"):
        mem.remember("    \n\t  ")

    with pytest.raises(ValueError, match="exceeds 500 characters"):
        mem.remember("a" * 501)

    # 500 characters should succeed
    res = mem.remember("a" * 500, kind="profile")
    assert res.startswith("Remembered (profile):")


def test_remember_dedupe_exact_and_near_dupe(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)

    mem.remember("Prefers tabs over spaces", kind="preference")

    # Exact match (case-insensitive)
    dupe1 = mem.remember("prefers tabs over spaces", kind="preference")
    assert dupe1 == "Already remembered: Prefers tabs over spaces"

    # Near dupe (> 0.9 difflib ratio)
    dupe2 = mem.remember("Prefers tabs over spaces!", kind="preference")
    assert dupe2 == "Already remembered: Prefers tabs over spaces"

    # Different text (ratio < 0.9) succeeds
    diff = mem.remember("Prefers spaces over tabs", kind="preference")
    assert diff == "Remembered (preference): Prefers spaces over tabs"

    # Same text in different file succeeds
    in_notes = mem.remember("Prefers tabs over spaces", kind="note", topic="coding")
    assert in_notes == "Remembered (note): Prefers tabs over spaces"


def test_core_text_empty(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)
    assert mem.core_text() == ""


def test_core_text_formatting_and_stripping_dates(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)
    mem.remember("Alice is a software engineer", kind="profile")
    mem.remember("Prefers Neovim as primary editor", kind="preference")

    core = mem.core_text(max_tokens=1000)
    assert "# Profile" in core
    assert "- Alice is a software engineer" in core
    assert "# Preferences" in core
    assert "- Prefers Neovim as primary editor" in core
    # Ensure date comments are stripped
    assert "<!--" not in core
    assert "-->" not in core
    assert "(older memories trimmed" not in core


def test_core_text_budget_trimming_drops_oldest(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)

    # Write files directly with explicit dated entries
    p_file = tmp_path / "profile.md"
    p_file.write_text(
        "# Profile\n\n"
        "- Very old profile entry 1  <!-- 2026-01-01 -->\n"
        "- Newer profile entry 2  <!-- 2026-05-01 -->\n",
        encoding="utf-8",
    )
    pref_file = tmp_path / "preferences.md"
    pref_file.write_text(
        "# Preferences\n\n"
        "- Middle preference entry 1  <!-- 2026-03-01 -->\n"
        "- Brand new preference entry 2  <!-- 2026-06-01 -->\n",
        encoding="utf-8",
    )

    full_text = mem.core_text(max_tokens=2000)
    full_tokens = util.estimate_tokens(full_text)

    # Request budget smaller than full tokens
    budget = full_tokens - 10
    trimmed_core = mem.core_text(max_tokens=budget)

    assert "(older memories trimmed - use recall)" in trimmed_core
    # Oldest entry (2026-01-01) should have been dropped first
    assert "Very old profile entry 1" not in trimmed_core
    # Newest entry (2026-06-01) should remain
    assert "Brand new preference entry 2" in trimmed_core
    assert util.estimate_tokens(trimmed_core) <= budget


def test_core_text_tiny_budget(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)
    mem.remember("Some profile data", kind="profile")
    # Budget too tiny to fit anything
    assert mem.core_text(max_tokens=1) == ""


def test_recall_bm25_ranking(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)

    mem.remember(
        "Alice is a systems engineer working on distributed backends",
        kind="profile",
    )
    mem.remember("Loves building services in async Python", kind="preference")
    mem.remember(
        "FastAPI is the primary framework for async Python REST services",
        kind="note",
        topic="python",
    )
    mem.remember(
        "Pytest provides unit testing fixtures for Python projects",
        kind="note",
        topic="python",
    )
    mem.remember(
        "Rust delivers high-performance memory safety without garbage collection",
        kind="note",
        topic="rust",
    )

    # 1. Query for FastAPI: top result should be from notes/python
    res = mem.recall("fastapi", k=3)
    assert len(res) >= 1
    assert res[0].startswith("[notes/python] FastAPI is the primary framework")

    # 2. Query with multiple terms ranking higher than single term
    res_multi = mem.recall("async python rest services", k=3)
    assert len(res_multi) >= 2
    # The note with both async python and rest services should score top
    assert "FastAPI" in res_multi[0]

    # 3. Query matching profile
    res_prof = mem.recall("distributed backends", k=1)
    assert len(res_prof) == 1
    assert res_prof[0].startswith("[profile] Alice is a systems engineer")

    # 4. Query matching nothing
    assert mem.recall("quantum supercomputing") == []
    assert mem.recall("") == []


def test_forget_removes_matching_entries_across_files(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)

    mem.remember("User loves Docker containers", kind="profile")
    mem.remember("Prefers Docker Compose for local development", kind="preference")
    mem.remember("Docker image optimization tips", kind="note", topic="devops")
    mem.remember("Kubernetes cluster setup", kind="note", topic="devops")

    count = mem.forget("docker")
    assert count == 3

    # All docker entries removed
    assert mem.recall("docker") == []

    # Kubernetes entry preserved
    k8s_match = mem.recall("kubernetes")
    assert len(k8s_match) == 1
    assert "Kubernetes cluster setup" in k8s_match[0]

    # Empty forget query
    assert mem.forget("") == 0
    assert mem.forget("   ") == 0


def test_lenient_parsing_of_hand_edited_files(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    custom_note = notes_dir / "custom.md"

    # Hand-edited file with comments, non-bullet lines, undated bullets
    raw_markdown = (
        "# Custom Title\n\n"
        "Here are user notes entered by hand:\n\n"
        "- First manual entry without date comment\n"
        "- Second manual entry with date  <!-- 2026-02-14 -->\n\n"
        "* Some asterisk bullet (not a dash bullet)\n"
        "<!-- Raw comment line -->\n\n"
        "- Third manual entry\n"
    )
    custom_note.write_text(raw_markdown, encoding="utf-8")

    # Recall should find manual entries
    recalled = mem.recall("manual")
    assert len(recalled) == 3

    # Remember a new entry - preserves all hand-edited lines
    mem.remember("Fourth entry added via agent", kind="note", topic="custom")
    after_remember = custom_note.read_text(encoding="utf-8")
    assert "Here are user notes entered by hand:" in after_remember
    assert "* Some asterisk bullet (not a dash bullet)" in after_remember
    assert "<!-- Raw comment line -->" in after_remember
    assert "- Fourth entry added via agent  <!-- " in after_remember

    # Forget removes only matching bullet and preserves human headers/comments
    removed = mem.forget("Second manual")
    assert removed == 1
    after_forget = custom_note.read_text(encoding="utf-8")
    assert "Second manual entry" not in after_forget
    assert "Here are user notes entered by hand:" in after_forget
    assert "* Some asterisk bullet (not a dash bullet)" in after_forget


def test_list_topics(tmp_path: Path) -> None:
    mem = Memory(directory=tmp_path)
    assert mem.list_topics() == []

    mem.remember("Python notes", kind="note", topic="python")
    mem.remember("Rust notes", kind="note", topic="rust")
    mem.remember("DevOps notes", kind="note", topic="devops")

    topics = mem.list_topics()
    assert topics == ["devops", "python", "rust"]


def test_default_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))
    mem = Memory()
    assert mem.directory == paths.memory_dir()
