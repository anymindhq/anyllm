"""Tests for the graphify bridge (graph_bridge.py)."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from anyllm.graph_bridge import (
    graphify_available,
    graphify_version,
    query_node_confidence,
    update_graph,
    graph_hash,
    graph_mtime,
    make_graph_query_fn,
)


# ---------------------------------------------------------------------------
# graphify_available
# ---------------------------------------------------------------------------

class TestGraphifyAvailable:
    def test_available_when_on_path(self):
        with patch("anyllm.graph_bridge.shutil.which", return_value="/usr/bin/graphify"):
            assert graphify_available() is True

    def test_not_available_when_missing(self):
        with patch("anyllm.graph_bridge.shutil.which", return_value=None):
            assert graphify_available() is False


# ---------------------------------------------------------------------------
# query_node_confidence
# ---------------------------------------------------------------------------

class TestQueryNodeConfidence:
    def test_graphify_not_available_returns_missing(self):
        with patch("anyllm.graph_bridge.graphify_available", return_value=False):
            assert query_node_confidence("graph.json", "auth.py") == "MISSING"

    def test_extracted_confidence(self, graph_response_extracted: dict):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(graph_response_extracted)

        with patch("anyllm.graph_bridge.graphify_available", return_value=True), \
             patch("anyllm.graph_bridge.subprocess.run", return_value=mock_result):
            result = query_node_confidence("graph.json", "validate_jwt")
            assert result == "EXTRACTED"

    def test_inferred_confidence(self, graph_response_inferred: dict):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(graph_response_inferred)

        with patch("anyllm.graph_bridge.graphify_available", return_value=True), \
             patch("anyllm.graph_bridge.subprocess.run", return_value=mock_result):
            result = query_node_confidence("graph.json", "CacheManager")
            assert result == "INFERRED"

    def test_missing_node(self, graph_response_missing: dict):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(graph_response_missing)

        with patch("anyllm.graph_bridge.graphify_available", return_value=True), \
             patch("anyllm.graph_bridge.subprocess.run", return_value=mock_result):
            result = query_node_confidence("graph.json", "deleted_func")
            assert result == "MISSING"

    def test_timeout_falls_back_gracefully(self):
        with patch("anyllm.graph_bridge.graphify_available", return_value=True), \
             patch("anyllm.graph_bridge.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="graphify", timeout=30)):
            result = query_node_confidence("graph.json", "auth.py", timeout=30)
            assert result == "MISSING"

    def test_nonzero_exit_returns_missing(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error: not found"

        with patch("anyllm.graph_bridge.graphify_available", return_value=True), \
             patch("anyllm.graph_bridge.subprocess.run", return_value=mock_result):
            result = query_node_confidence("graph.json", "auth.py")
            assert result == "MISSING"

    def test_invalid_json_returns_missing(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json at all"

        with patch("anyllm.graph_bridge.graphify_available", return_value=True), \
             patch("anyllm.graph_bridge.subprocess.run", return_value=mock_result):
            result = query_node_confidence("graph.json", "auth.py")
            assert result == "MISSING"

    def test_query_parses_confidence_correctly(self):
        """Test all valid confidence values are parsed correctly."""
        for confidence in ("EXTRACTED", "INFERRED", "AMBIGUOUS"):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps({"exists": True, "confidence": confidence})

            with patch("anyllm.graph_bridge.graphify_available", return_value=True), \
                 patch("anyllm.graph_bridge.subprocess.run", return_value=mock_result):
                result = query_node_confidence("graph.json", "test")
                assert result == confidence


# ---------------------------------------------------------------------------
# update_graph
# ---------------------------------------------------------------------------

class TestUpdateGraph:
    def test_not_installed_returns_false(self):
        with patch("anyllm.graph_bridge.graphify_available", return_value=False):
            assert update_graph("/project") is False

    def test_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("anyllm.graph_bridge.graphify_available", return_value=True), \
             patch("anyllm.graph_bridge.subprocess.run", return_value=mock_result):
            assert update_graph("/project") is True

    def test_timeout_returns_false(self):
        with patch("anyllm.graph_bridge.graphify_available", return_value=True), \
             patch("anyllm.graph_bridge.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="graphify", timeout=30)):
            assert update_graph("/project", timeout=30) is False

    def test_failure_returns_false(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"

        with patch("anyllm.graph_bridge.graphify_available", return_value=True), \
             patch("anyllm.graph_bridge.subprocess.run", return_value=mock_result):
            assert update_graph("/project") is False


# ---------------------------------------------------------------------------
# Graph metadata
# ---------------------------------------------------------------------------

class TestGraphMetadata:
    def test_hash_nonexistent_file(self):
        assert graph_hash("/nonexistent/graph.json") is None

    def test_hash_real_file(self, tmp_path):
        f = tmp_path / "graph.json"
        f.write_text('{"nodes": []}')
        h = graph_hash(str(f))
        assert h is not None
        assert h.startswith("sha256:")

    def test_mtime_nonexistent_file(self):
        assert graph_mtime("/nonexistent/graph.json") is None

    def test_mtime_real_file(self, tmp_path):
        f = tmp_path / "graph.json"
        f.write_text('{"nodes": []}')
        mt = graph_mtime(str(f))
        assert mt is not None


# ---------------------------------------------------------------------------
# make_graph_query_fn
# ---------------------------------------------------------------------------

class TestMakeGraphQueryFn:
    def test_returns_callable(self):
        fn = make_graph_query_fn("graph.json")
        assert callable(fn)

    def test_callable_delegates_to_query(self):
        with patch("anyllm.graph_bridge.query_node_confidence", return_value="EXTRACTED") as mock:
            fn = make_graph_query_fn("graph.json", timeout=10)
            result = fn("auth.py")
            assert result == "EXTRACTED"
            mock.assert_called_once_with("graph.json", "auth.py", timeout=10)
