from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .base import Ingestor, NormalizedTranscript


CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# Tool names whose inputs identify files that were read/written/edited.
FILE_TOOLS = {"Edit", "Write", "NotebookEdit", "Read", "MultiEdit"}


def _project_slug(project_root: Path) -> str:
    """Claude Code encodes project directories as `/foo/bar` → `-foo-bar`.

    On Windows, resolved paths look like `C:\\Users\\foo\\bar`, which Claude
    Code encodes as `C--Users-foo-bar` (both `:` and `\\` become `-`).
    """
    s = str(project_root.resolve())
    for ch in ("/", "\\", ":"):
        s = s.replace(ch, "-")
    return s


def _flatten_content(content: Any) -> tuple[str, list[dict[str, Any]]]:
    """Extract plain text and structured tool_use blocks from an assistant message."""
    if isinstance(content, str):
        return content, []
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append({
                    "name": block.get("name"),
                    "input": block.get("input"),
                })
    return "\n".join(p for p in text_parts if p), tool_calls


def _extract_files(tool_calls: Iterable[dict[str, Any]]) -> list[str]:
    files: list[str] = []
    for tc in tool_calls:
        if tc.get("name") in FILE_TOOLS:
            inp = tc.get("input") or {}
            fp = inp.get("file_path") or inp.get("notebook_path")
            if fp:
                files.append(str(fp))
    return files


class ClaudeCodeIngestor:
    name = "claude-code"

    def __init__(self, projects_root: Path = CLAUDE_PROJECTS):
        self.projects_root = projects_root

    def _session_files(self, project_root: Path) -> list[Path]:
        slug_dir = self.projects_root / _project_slug(project_root)
        if not slug_dir.is_dir():
            return []
        return sorted(slug_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)

    def latest_session(self, project_root: Path) -> NormalizedTranscript | None:
        files = self._session_files(project_root)
        if not files:
            return None
        return self._normalize(files[-1])

    def session_by_id(self, project_root: Path, session_id: str) -> NormalizedTranscript | None:
        for p in self._session_files(project_root):
            if p.stem == session_id:
                return self._normalize(p)
        return None

    def _normalize(self, jsonl_path: Path) -> NormalizedTranscript:
        turns: list[dict[str, Any]] = []
        files_touched: list[str] = []
        model: str | None = None
        session_id = jsonl_path.stem
        started_at = ""
        ended_at = ""
        token_count = 0

        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue

                rtype = row.get("type")
                ts = row.get("timestamp", "")
                if ts:
                    if not started_at:
                        started_at = ts
                    ended_at = ts

                if rtype not in ("user", "assistant"):
                    continue

                msg = row.get("message") or {}
                role = msg.get("role", rtype)
                content = msg.get("content", "")
                text, tool_calls = _flatten_content(content)
                files_touched.extend(_extract_files(tool_calls))

                usage = msg.get("usage") or {}
                if usage:
                    token_count += int(usage.get("input_tokens", 0) or 0)
                    token_count += int(usage.get("output_tokens", 0) or 0)
                if model is None and msg.get("model"):
                    model = msg["model"]

                turn: dict[str, Any] = {"role": role, "text": text, "ts": ts}
                if tool_calls:
                    turn["tool_calls"] = tool_calls
                turns.append(turn)

        # Deduplicate files_touched preserving order.
        seen: set[str] = set()
        unique_files = []
        for fp in files_touched:
            if fp not in seen:
                seen.add(fp)
                unique_files.append(fp)

        return NormalizedTranscript(
            source=self.name,
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            turns=turns,
            files_touched=unique_files,
            metadata={
                "model": model,
                "token_count": token_count,
                "source_path": str(jsonl_path),
            },
        )
