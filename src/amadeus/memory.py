"""Persistent user memory for Amadeus.

Stores user profile, preferences, and topical notes in Markdown files
with lenient, human-editable parsing and BM25-lite keyword recall.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from amadeus import paths, util

# Standard short English stopwords to ignore during keyword recall tokenization
SHORT_STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "but",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "him",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "me",
    "my",
    "no",
    "not",
    "of",
    "on",
    "or",
    "our",
    "she",
    "so",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "to",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "you",
    "your",
}

_DATE_RE = re.compile(r"<!--\s*(\d{4}-\d{2}-\d{2})\s*-->")
_DATE_STRIP_RE = re.compile(r"\s*<!--.*?-->")


@dataclass
class MemoryEntry:
    raw_line: str
    text: str
    date: str | None
    source: str
    order: int


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"\w+", text.lower())
    filtered = [w for w in words if w not in SHORT_STOPWORDS]
    return filtered if filtered else words


def _parse_entry_line(line: str, source: str, order: int) -> MemoryEntry | None:
    if not line.startswith("- "):
        return None
    body = line[2:]
    date_match = _DATE_RE.search(body)
    date_str = date_match.group(1) if date_match else None
    clean_text = _DATE_STRIP_RE.sub("", body).strip()
    return MemoryEntry(raw_line=line, text=clean_text, date=date_str, source=source, order=order)


class Memory:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else paths.memory_dir()
        self.notes_dir = self.directory / "notes"

    def _slugify(self, topic: str | None) -> str:
        if not topic or not topic.strip():
            return "general"
        slug = re.sub(r"[^\w\-]+", "-", topic.strip().lower()).strip("-")
        return slug or "general"

    def _read_entries(self, file_path: Path, source: str) -> list[MemoryEntry]:
        if not file_path.is_file():
            return []
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return []
        entries: list[MemoryEntry] = []
        for idx, line in enumerate(content.splitlines()):
            entry = _parse_entry_line(line, source, idx)
            if entry is not None and entry.text:
                entries.append(entry)
        return entries

    def remember(
        self,
        text: str,
        kind: Literal["profile", "preference", "note"] = "note",
        topic: str | None = None,
    ) -> str:
        # 1. Normalise whitespace
        normalised = " ".join(text.split())

        # 2. Reject empty / >500 chars
        if not normalised:
            raise ValueError("Memory text cannot be empty.")
        if len(normalised) > 500:
            raise ValueError(f"Memory text exceeds 500 characters ({len(normalised)}).")

        # 3. Resolve target file & title
        if kind == "profile":
            target_path = self.directory / "profile.md"
            source = "profile"
            title = "# Profile"
        elif kind == "preference":
            target_path = self.directory / "preferences.md"
            source = "preferences"
            title = "# Preferences"
        elif kind == "note":
            slug = self._slugify(topic)
            target_path = self.notes_dir / f"{slug}.md"
            source = f"notes/{slug}"
            topic_title = topic.strip() if topic and topic.strip() else "General"
            title = f"# Notes: {topic_title}"
        else:
            raise ValueError(f"Invalid memory kind: {kind}")

        # 4. Dedupe against existing entries in the same file
        existing_entries = self._read_entries(target_path, source)
        for existing in existing_entries:
            if normalised.lower() == existing.text.lower():
                return f"Already remembered: {existing.text}"
            ratio = difflib.SequenceMatcher(None, normalised.lower(), existing.text.lower()).ratio()
            if ratio > 0.9:
                return f"Already remembered: {existing.text}"

        # 5. Append new entry
        today = datetime.now().strftime("%Y-%m-%d")
        bullet = f"- {normalised}  <!-- {today} -->"

        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.is_file():
            content = target_path.read_text(encoding="utf-8")
            if content and not content.endswith("\n"):
                content += "\n"
            content += f"{bullet}\n"
        else:
            content = f"{title}\n\n{bullet}\n"

        target_path.write_text(content, encoding="utf-8", newline="\n")
        return f"Remembered ({kind}): {normalised}"

    def core_text(self, max_tokens: int = 1200) -> str:
        p_path = self.directory / "profile.md"
        pref_path = self.directory / "preferences.md"

        p_entries = self._read_entries(p_path, "profile")
        pref_entries = self._read_entries(pref_path, "preferences")

        if not p_entries and not pref_entries:
            return ""

        def _format(p_list: list[MemoryEntry], pref_list: list[MemoryEntry], trimmed: bool) -> str:
            sections: list[str] = []
            if p_list:
                lines = ["# Profile"]
                for e in p_list:
                    lines.append(f"- {e.text}")
                sections.append("\n".join(lines))
            if pref_list:
                lines = ["# Preferences"]
                for e in pref_list:
                    lines.append(f"- {e.text}")
                sections.append("\n".join(lines))
            if not sections:
                return ""
            rendered = "\n\n".join(sections)
            if trimmed:
                rendered += "\n\n(older memories trimmed - use recall)"
            return rendered

        full_rendered = _format(p_entries, pref_entries, trimmed=False)
        if util.estimate_tokens(full_rendered) <= max_tokens:
            return full_rendered

        # Budget exceeded: drop oldest entries first
        active_p = list(p_entries)
        active_pref = list(pref_entries)

        while active_p or active_pref:
            candidate = _format(active_p, active_pref, trimmed=True)
            if util.estimate_tokens(candidate) <= max_tokens:
                return candidate

            # Compare oldest entry between active_p and active_pref
            oldest_choice: Literal["profile", "preference"]
            if active_p and not active_pref:
                oldest_choice = "profile"
            elif active_pref and not active_p:
                oldest_choice = "preference"
            else:
                p_oldest = active_p[0]
                pref_oldest = active_pref[0]
                p_date = p_oldest.date or "0000-00-00"
                pref_date = pref_oldest.date or "0000-00-00"
                if p_date <= pref_date:
                    oldest_choice = "profile"
                else:
                    oldest_choice = "preference"

            if oldest_choice == "profile":
                active_p.pop(0)
            else:
                active_pref.pop(0)

        return ""

    def recall(self, query: str, k: int = 5) -> list[str]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        all_entries: list[MemoryEntry] = []
        if (self.directory / "profile.md").is_file():
            all_entries.extend(self._read_entries(self.directory / "profile.md", "profile"))
        if (self.directory / "preferences.md").is_file():
            all_entries.extend(self._read_entries(self.directory / "preferences.md", "preferences"))
        if self.notes_dir.is_dir():
            for note_file in sorted(self.notes_dir.glob("*.md")):
                if note_file.is_file():
                    all_entries.extend(self._read_entries(note_file, f"notes/{note_file.stem}"))

        if not all_entries:
            return []

        doc_tokens_list: list[list[str]] = [_tokenize(e.text) for e in all_entries]
        n_docs = len(all_entries)
        avgdl = sum(len(dt) for dt in doc_tokens_list) / n_docs if n_docs > 0 else 1.0
        if avgdl == 0:
            avgdl = 1.0

        k1 = 1.2
        b = 0.75

        # Document frequencies & IDF
        q_token_set = set(q_tokens)
        idfs: dict[str, float] = {}
        for qt in q_token_set:
            df = sum(1 for dt in doc_tokens_list if qt in dt)
            if df > 0:
                idfs[qt] = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            else:
                idfs[qt] = 0.0

        scored: list[tuple[float, MemoryEntry]] = []
        for entry, dt in zip(all_entries, doc_tokens_list, strict=True):
            score = 0.0
            doc_len = len(dt)
            for qt in q_tokens:
                idf = idfs.get(qt, 0.0)
                if idf <= 0.0:
                    continue
                tf = dt.count(qt)
                if tf > 0:
                    score += idf * (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * (doc_len / avgdl)))
            if score > 0.0:
                scored.append((score, entry))

        if not scored:
            return []

        scored.sort(key=lambda x: x[0], reverse=True)
        top_entries = scored[:k]

        return [f"[{e.source}] {e.text}" for _, e in top_entries]

    def forget(self, text: str) -> int:
        query = text.strip().lower()
        if not query:
            return 0

        target_files: list[Path] = []
        if (self.directory / "profile.md").is_file():
            target_files.append(self.directory / "profile.md")
        if (self.directory / "preferences.md").is_file():
            target_files.append(self.directory / "preferences.md")
        if self.notes_dir.is_dir():
            for note_file in sorted(self.notes_dir.glob("*.md")):
                if note_file.is_file():
                    target_files.append(note_file)

        total_removed = 0

        for file_path in target_files:
            try:
                content = file_path.read_text(encoding="utf-8")
            except OSError:
                continue

            lines = content.splitlines()
            kept_lines: list[str] = []
            removed_in_file = 0

            for line in lines:
                if line.startswith("- "):
                    body = line[2:]
                    clean_text = _DATE_STRIP_RE.sub("", body).strip()
                    if query in clean_text.lower():
                        removed_in_file += 1
                        continue
                kept_lines.append(line)

            if removed_in_file > 0:
                total_removed += removed_in_file
                new_content = "\n".join(kept_lines)
                if new_content and not new_content.endswith("\n"):
                    new_content += "\n"
                file_path.write_text(new_content, encoding="utf-8", newline="\n")

        return total_removed

    def list_topics(self) -> list[str]:
        if not self.notes_dir.is_dir():
            return []
        return sorted(p.stem for p in self.notes_dir.glob("*.md") if p.is_file())
