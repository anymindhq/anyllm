"""Tests for storage-level merge integration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from anyllm.storage import Paths, write_merged_current, write_current


class TestWriteMergedCurrent:
    def test_first_session_writes_directly(self, tmp_project: Path, snapshot_v1: str):
        paths = Paths(root=tmp_project)
        assert not paths.current_path.exists()

        result_path, merge_result = write_merged_current(
            paths, snapshot_v1, session_id="session-1"
        )

        assert result_path.exists()
        assert merge_result is None  # no merge on first session
        assert paths.current_path.read_text() == snapshot_v1

    def test_current_md_contains_all_session_decisions(
        self, tmp_project: Path, snapshot_v1: str, snapshot_v2: str
    ):
        paths = Paths(root=tmp_project)

        # First session
        write_merged_current(paths, snapshot_v1, session_id="2025-06-18-def456")

        # Second session — should merge
        _, merge_result = write_merged_current(
            paths, snapshot_v2, session_id="2025-06-19-ghi789"
        )

        assert merge_result is not None
        current = paths.current_path.read_text()

        # Should contain decisions from both sessions
        assert "[CONFIRMED" in current
        # New decisions should be tagged
        total = len(merge_result.confirmed) + len(merge_result.added)
        assert total >= 5  # v1 had 5, v2 adds at least 1

    def test_merged_from_frontmatter_updated(
        self, tmp_project: Path, snapshot_v1: str, snapshot_v2: str
    ):
        paths = Paths(root=tmp_project)

        write_merged_current(paths, snapshot_v1, session_id="2025-06-18-def456")
        write_merged_current(paths, snapshot_v2, session_id="2025-06-19-ghi789")

        current = paths.current_path.read_text()
        assert "2025-06-19-ghi789" in current
        assert "merged_from" in current

    def test_three_sessions_accumulate(
        self,
        tmp_project: Path,
        snapshot_v1: str,
        snapshot_v2: str,
        snapshot_v3: str,
    ):
        paths = Paths(root=tmp_project)

        write_merged_current(paths, snapshot_v1, session_id="2025-06-18-def456")
        write_merged_current(paths, snapshot_v2, session_id="2025-06-19-ghi789")
        _, result = write_merged_current(
            paths, snapshot_v3, session_id="2025-06-21-abc123"
        )

        assert result is not None
        current = paths.current_path.read_text()

        # All session IDs should be in merged_from
        assert "2025-06-19-ghi789" in current
        assert "2025-06-21-abc123" in current

        # Total decisions should reflect accumulation
        total = len(result.confirmed) + len(result.added) + len(result.stale)
        assert total >= 4

    def test_failed_approaches_never_lost(
        self,
        tmp_project: Path,
        snapshot_v1: str,
        snapshot_v2: str,
        snapshot_v3: str,
    ):
        paths = Paths(root=tmp_project)

        write_merged_current(paths, snapshot_v1, session_id="2025-06-18-def456")
        write_merged_current(paths, snapshot_v2, session_id="2025-06-19-ghi789")
        write_merged_current(paths, snapshot_v3, session_id="2025-06-21-abc123")

        current = paths.current_path.read_text().lower()
        # passport from v1, memory from v2, sha from v3
        assert "passport" in current
        assert "sha-256" in current or "sha-1" in current

    def test_merge_with_graph_query(self, tmp_project: Path, snapshot_v1: str, snapshot_v3: str):
        """Graph queries influence decision classification."""
        paths = Paths(root=tmp_project)

        write_merged_current(paths, snapshot_v1, session_id="2025-06-18-def456")

        def mock_graph(anchor: str) -> str:
            if anchor in ("RateLimiter", "middleware.py"):
                return "EXTRACTED"
            return "MISSING"

        _, result = write_merged_current(
            paths,
            snapshot_v3,
            session_id="2025-06-21-abc123",
            graph_path="fake/graph.json",
            graph_query_fn=mock_graph,
        )

        assert result is not None
        # RateLimiter should be CONFIRMED (EXTRACTED by graph) despite being absent from v3
        rate_limiter_confirmed = any(
            "RateLimiter" in d.text or "rate limit" in d.text.lower()
            for d in result.confirmed
        )
        assert rate_limiter_confirmed


class TestWriteCurrentLegacy:
    def test_clobber_behavior(self, tmp_project: Path, snapshot_v1: str, snapshot_v2: str):
        """Legacy write_current should still clobber."""
        paths = Paths(root=tmp_project)

        write_current(paths, snapshot_v1)
        assert paths.current_path.read_text() == snapshot_v1

        write_current(paths, snapshot_v2)
        assert paths.current_path.read_text() == snapshot_v2
