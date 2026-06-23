"""Tests for the merge engine (merger.py)."""
from __future__ import annotations

import pytest

from anyllm.merger import (
    Decision,
    MergeEngine,
    MergeResult,
    bigram_similarity,
    decision_id,
    extract_code_anchor,
    match_decisions,
    parse_decisions,
)


# ---------------------------------------------------------------------------
# Decision parsing
# ---------------------------------------------------------------------------

class TestParseDecisions:
    def test_basic_extraction(self, snapshot_v1: str):
        decisions = parse_decisions(snapshot_v1)
        assert len(decisions) == 5

    def test_extracts_code_anchors(self, snapshot_v1: str):
        decisions = parse_decisions(snapshot_v1)
        anchors = [d.code_anchor for d in decisions]
        # `auth.py` (file path) wins over `validate_jwt()` (function) in same decision
        assert "auth.py" in anchors
        assert "config.py" in anchors

    def test_extracts_from_tagged_decisions(self):
        md = """## Decisions
- [CONFIRMED | auth.py] JWT validation lives in `validate_jwt()`.
- [NEW] Switched to `httpx` for async HTTP.
"""
        decisions = parse_decisions(md)
        assert len(decisions) == 2
        # Tags should be stripped for ID calculation but preserved in text
        assert "CONFIRMED" in decisions[0].text
        assert "NEW" in decisions[1].text

    def test_empty_decisions_section(self):
        md = """## Decisions
"""
        assert parse_decisions(md) == []

    def test_no_decisions_section(self):
        md = """## Task
Some task description
"""
        assert parse_decisions(md) == []

    def test_html_comments_skipped(self):
        md = """## Decisions
<!-- CONFIRMED: verified by graph -->
- Decision one about `auth.py`.
<!-- ADDED: new this session -->
- Decision two about `config.py`.
"""
        decisions = parse_decisions(md)
        assert len(decisions) == 2


# ---------------------------------------------------------------------------
# Code anchor extraction
# ---------------------------------------------------------------------------

class TestExtractCodeAnchor:
    def test_backtick_filepath(self):
        assert extract_code_anchor("Moved logic into `src/auth.py`") == "src/auth.py"

    def test_backtick_function(self):
        assert extract_code_anchor("Using `validate_jwt()` for tokens") == "validate_jwt"

    def test_backtick_class(self):
        assert extract_code_anchor("The `RateLimiter` class handles throttling") == "RateLimiter"

    def test_bare_filepath(self):
        result = extract_code_anchor("Config is in config.py for settings")
        assert result == "config.py"

    def test_no_anchor(self):
        assert extract_code_anchor("This is a plain decision without code refs") is None


# ---------------------------------------------------------------------------
# Decision identity hashing
# ---------------------------------------------------------------------------

class TestDecisionId:
    def test_stable_across_calls(self):
        assert decision_id("some decision text") == decision_id("some decision text")

    def test_case_insensitive(self):
        assert decision_id("JWT validation in auth.py") == decision_id("jwt validation in auth.py")

    def test_punctuation_insensitive(self):
        assert decision_id("JWT validation, in auth.py!") == decision_id("JWT validation in authpy")

    def test_different_text_different_id(self):
        assert decision_id("decision A") != decision_id("decision B")


# ---------------------------------------------------------------------------
# Bigram similarity
# ---------------------------------------------------------------------------

class TestBigramSimilarity:
    def test_identical(self):
        assert bigram_similarity("hello world", "hello world") == 1.0

    def test_empty(self):
        assert bigram_similarity("", "") == 0.0

    def test_similar_paraphrase(self):
        sim = bigram_similarity(
            "JWT validation was moved into validate_jwt inside auth.py",
            "Authentication is handled by the auth module with validate_jwt for token verification",
        )
        # Should show reasonable similarity due to shared terms
        assert sim > 0.2

    def test_completely_different(self):
        sim = bigram_similarity("apple banana cherry", "xyz 123 hello")
        assert sim < 0.2


# ---------------------------------------------------------------------------
# Decision matching
# ---------------------------------------------------------------------------

class TestMatchDecisions:
    def test_same_decision_reworded_is_matched(self, snapshot_v1: str, snapshot_v2: str):
        old = parse_decisions(snapshot_v1)
        new = parse_decisions(snapshot_v2)
        matched, unmatched_old, unmatched_new = match_decisions(old, new)
        # Most decisions should match between v1 and v2
        assert len(matched) >= 4

    def test_new_decision_detected(self, snapshot_v1: str, snapshot_v2: str):
        old = parse_decisions(snapshot_v1)
        new = parse_decisions(snapshot_v2)
        _, _, unmatched_new = match_decisions(old, new)
        # v2 adds token_store decision
        assert len(unmatched_new) >= 1

    def test_identical_decisions_all_match(self):
        md = """## Decisions
- Using `auth.py` for JWT validation.
- Database pool is 10 connections.
"""
        old = parse_decisions(md)
        new = parse_decisions(md)
        matched, unmatched_old, unmatched_new = match_decisions(old, new)
        assert len(matched) == 2
        assert len(unmatched_old) == 0
        assert len(unmatched_new) == 0


# ---------------------------------------------------------------------------
# MergeEngine — text-only (no graph)
# ---------------------------------------------------------------------------

class TestMergeEngineTextOnly:
    def test_same_decision_reworded_is_confirmed(self, snapshot_v1: str, snapshot_v2: str):
        engine = MergeEngine()
        result = engine.merge(snapshot_v1, snapshot_v2, session_id="2025-06-19-ghi789")
        assert len(result.confirmed) >= 4

    def test_new_decision_is_added(self, snapshot_v1: str, snapshot_v2: str):
        engine = MergeEngine()
        result = engine.merge(snapshot_v1, snapshot_v2, session_id="2025-06-19-ghi789")
        assert len(result.added) >= 1

    def test_dropped_decision_becomes_stale(self, snapshot_v1: str, snapshot_v3: str):
        engine = MergeEngine()
        result = engine.merge(snapshot_v1, snapshot_v3, session_id="2025-06-21-abc123")
        # RateLimiter decision is in v1 but not in v3
        assert len(result.stale) >= 1

    def test_merged_md_contains_confirmed_tag(self, snapshot_v1: str, snapshot_v2: str):
        engine = MergeEngine()
        result = engine.merge(snapshot_v1, snapshot_v2, session_id="2025-06-19-ghi789")
        assert "[CONFIRMED" in result.merged_md

    def test_merged_md_contains_new_tag(self, snapshot_v1: str, snapshot_v2: str):
        engine = MergeEngine()
        result = engine.merge(snapshot_v1, snapshot_v2, session_id="2025-06-19-ghi789")
        assert "[NEW]" in result.merged_md

    def test_merged_md_has_merged_from(self, snapshot_v1: str, snapshot_v2: str):
        engine = MergeEngine()
        result = engine.merge(snapshot_v1, snapshot_v2, session_id="2025-06-19-ghi789")
        assert "merged_from" in result.merged_md
        assert "2025-06-19-ghi789" in result.merged_md

    def test_merged_md_has_confidence_report_frontmatter(self, snapshot_v1: str, snapshot_v2: str):
        engine = MergeEngine()
        result = engine.merge(snapshot_v1, snapshot_v2, session_id="2025-06-19-ghi789")
        assert "confidence_report" in result.merged_md

    def test_failed_approaches_never_dropped(self, snapshot_v1: str, snapshot_v3: str):
        engine = MergeEngine()
        result = engine.merge(snapshot_v1, snapshot_v3, session_id="2025-06-21-abc123")
        # Both v1 and v3 have different failed approaches; both should survive
        assert "passport.js" in result.merged_md.lower() or "passport" in result.merged_md.lower()
        assert "SHA-256" in result.merged_md or "sha-256" in result.merged_md.lower()

    def test_open_questions_carry_forward(self, snapshot_v1: str, snapshot_v2: str):
        engine = MergeEngine()
        result = engine.merge(snapshot_v1, snapshot_v2, session_id="2025-06-19-ghi789")
        # v1 has PKCE question, v2 doesn't (resolved). But token expiry question persists.
        assert "token expiry" in result.merged_md.lower() or "expiry" in result.merged_md.lower()

    def test_stale_threshold_respected(self):
        """Decision absent for fewer sessions than threshold stays STALE, not ORPHANED."""
        md1 = """---
session_id: session-1
decision_provenance:
  validate_jwt:
    introduced: session-1
    confirmed_in: [session-1]
    sessions_absent: 0
    confidence: UNKNOWN
---
## Decisions
- Using `validate_jwt()` for authentication.
- Using `old_function()` that will be dropped.
"""
        md2 = """---
session_id: session-2
---
## Decisions
- Using `validate_jwt()` for authentication.
"""
        engine = MergeEngine(stale_threshold=3)
        result = engine.merge(md1, md2, session_id="session-2")
        # old_function is absent but below threshold → stale, not orphaned
        assert len(result.stale) >= 1
        assert len(result.orphaned) == 0

    def test_session_provenance_table(self, snapshot_v1: str, snapshot_v2: str):
        engine = MergeEngine()
        result = engine.merge(snapshot_v1, snapshot_v2, session_id="2025-06-19-ghi789")
        assert "## Session Provenance" in result.merged_md
        assert "Decision anchor" in result.merged_md


# ---------------------------------------------------------------------------
# MergeEngine — with graph
# ---------------------------------------------------------------------------

class TestMergeEngineWithGraph:
    def test_extracted_decision_survives_absence(self, snapshot_v1: str, snapshot_v3: str):
        """A decision absent from new snapshot but EXTRACTED by graph stays CONFIRMED."""
        def mock_graph_query(anchor: str) -> str:
            if anchor in ("RateLimiter", "middleware.py"):
                return "EXTRACTED"
            return "MISSING"

        engine = MergeEngine(graph_query_fn=mock_graph_query)
        result = engine.merge(
            snapshot_v1, snapshot_v3,
            session_id="2025-06-21-abc123",
            graph_path="fake/graph.json",
        )
        # RateLimiter decision should be CONFIRMED (pinned by graph)
        rate_limiter_confirmed = any(
            "RateLimiter" in d.text or "rate limit" in d.text.lower()
            for d in result.confirmed
        )
        assert rate_limiter_confirmed, "EXTRACTED decision should survive absence"

    def test_missing_node_decision_becomes_orphaned(self):
        """A decision about a deleted code node becomes ORPHANED after threshold."""
        md1 = """---
session_id: session-1
decision_provenance:
  deleted_module:
    introduced: session-1
    confirmed_in: [session-1]
    sessions_absent: 2
    confidence: UNKNOWN
---
## Decisions
- The `deleted_module` handles caching logic.
- Using `auth.py` for authentication.
"""
        md2 = """---
session_id: session-4
---
## Decisions
- Using `auth.py` for authentication.
"""

        def mock_graph_query(anchor: str) -> str:
            if anchor == "deleted_module":
                return "MISSING"
            return "EXTRACTED"

        engine = MergeEngine(stale_threshold=3, graph_query_fn=mock_graph_query)
        result = engine.merge(md1, md2, session_id="session-4", graph_path="fake.json")
        # deleted_module: sessions_absent was 2, now +1 = 3 >= threshold → ORPHANED
        assert len(result.orphaned) >= 1

    def test_inferred_decision_becomes_stale(self):
        """A decision with INFERRED confidence goes to STALE."""
        md1 = """---
session_id: session-1
---
## Decisions
- `CacheManager` wraps Redis for caching.
- Using `auth.py` for authentication.
"""
        md2 = """---
session_id: session-2
---
## Decisions
- Using `auth.py` for authentication.
"""

        def mock_graph_query(anchor: str) -> str:
            if anchor == "CacheManager":
                return "INFERRED"
            return "EXTRACTED"

        engine = MergeEngine(graph_query_fn=mock_graph_query)
        result = engine.merge(md1, md2, session_id="session-2", graph_path="fake.json")
        assert len(result.stale) >= 1
        stale_texts = [d.text for d in result.stale]
        assert any("CacheManager" in t for t in stale_texts)

    def test_no_graph_falls_back_to_stale(self, snapshot_v1: str, snapshot_v3: str):
        """Without graph, absent decisions go to STALE (conservative), not ORPHANED."""
        engine = MergeEngine()  # no graph_query_fn
        result = engine.merge(snapshot_v1, snapshot_v3, session_id="2025-06-21-abc123")
        # Absent decisions with no graph → STALE (not orphaned) if under threshold
        assert len(result.orphaned) == 0


# ---------------------------------------------------------------------------
# Three-session merge (integration-style)
# ---------------------------------------------------------------------------

class TestThreeSessionMerge:
    def test_three_sessions_accumulate(
        self, snapshot_v1: str, snapshot_v2: str, snapshot_v3: str
    ):
        engine = MergeEngine()

        # Session 1 → 2
        r1 = engine.merge(snapshot_v1, snapshot_v2, session_id="2025-06-19-ghi789")

        # Session 2 → 3 (merge result of 1+2 with 3)
        r2 = engine.merge(r1.merged_md, snapshot_v3, session_id="2025-06-21-abc123")

        # The final merged_md should reference all sessions
        assert "2025-06-19-ghi789" in r2.merged_md
        assert "2025-06-21-abc123" in r2.merged_md

        # Decisions from all sessions should be present (confirmed or stale)
        total_decisions = len(r2.confirmed) + len(r2.added) + len(r2.stale)
        assert total_decisions >= 4  # should have accumulated knowledge

    def test_failed_approaches_accumulate(
        self, snapshot_v1: str, snapshot_v2: str, snapshot_v3: str
    ):
        engine = MergeEngine()
        r1 = engine.merge(snapshot_v1, snapshot_v2, session_id="2025-06-19-ghi789")
        r2 = engine.merge(r1.merged_md, snapshot_v3, session_id="2025-06-21-abc123")
        # All failed approaches from all sessions should be present
        lower_md = r2.merged_md.lower()
        assert "passport" in lower_md  # from v1
        assert "sha-256" in lower_md or "sha-1" in lower_md  # from v3

    def test_superseded_decision_tracked(
        self, snapshot_v1: str, snapshot_v3: str
    ):
        engine = MergeEngine()
        result = engine.merge(snapshot_v1, snapshot_v3, session_id="2025-06-21-abc123")
        # v1 says `requests`, v3 says `httpx` — the transition should be tracked
        # Either as superseded or as updated
        lower_md = result.merged_md.lower()
        assert "httpx" in lower_md
