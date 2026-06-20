"""Thin bridge to the graphify CLI for codebase graph queries.

graphify is an *optional* dependency installed separately by the user.
All interaction happens via subprocess calls to the ``graphify`` CLI.
No graphify imports occur at module load time — anyllm runs normally
without graphify installed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default timeout for graphify subprocess calls (seconds).
DEFAULT_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def graphify_available() -> bool:
    """Check if the ``graphify`` CLI is on PATH."""
    return shutil.which("graphify") is not None


def graphify_version() -> str | None:
    """Return the installed graphify version string, or *None*."""
    if not graphify_available():
        return None
    try:
        result = subprocess.run(
            ["graphify", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Graph queries
# ---------------------------------------------------------------------------

def query_node_confidence(
    graph_path: str,
    anchor: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Query graphify for a code anchor's confidence level.

    Calls::

        graphify query "<anchor>" --graph <graph_path> --json

    Returns one of ``EXTRACTED``, ``INFERRED``, ``AMBIGUOUS``, or ``MISSING``.
    Falls back to ``MISSING`` if graphify is not available, the query fails,
    or the command times out.
    """
    if not graphify_available():
        return "MISSING"

    try:
        result = subprocess.run(
            ["graphify", "query", anchor, "--graph", graph_path, "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("graphify query timed out after %ds for anchor %r", timeout, anchor)
        return "MISSING"
    except Exception as exc:
        logger.warning("graphify query failed for anchor %r: %s", anchor, exc)
        return "MISSING"

    if result.returncode != 0:
        logger.debug("graphify query returned %d: %s", result.returncode, result.stderr.strip())
        return "MISSING"

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("graphify query returned non-JSON output for anchor %r", anchor)
        return "MISSING"

    if not data.get("exists", False):
        return "MISSING"

    confidence = data.get("confidence", "MISSING").upper()
    if confidence in ("EXTRACTED", "INFERRED", "AMBIGUOUS"):
        return confidence
    return "MISSING"


# ---------------------------------------------------------------------------
# Graph update
# ---------------------------------------------------------------------------

def update_graph(
    project_path: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> bool:
    """Run incremental graph extraction on the project.

    Calls::

        graphify extract <project_path> --update

    Only re-extracts files changed since the last run.  Returns ``True`` on
    success.  Safe to call — no-ops if graphify is not installed.
    """
    if not graphify_available():
        logger.debug("graphify not installed; skipping graph update")
        return False

    try:
        result = subprocess.run(
            ["graphify", "extract", project_path, "--update"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("graphify extract timed out after %ds", timeout)
        return False
    except Exception as exc:
        logger.warning("graphify extract failed: %s", exc)
        return False

    if result.returncode != 0:
        logger.warning("graphify extract returned %d: %s", result.returncode, result.stderr.strip())
        return False

    logger.info("graphify graph updated for %s", project_path)
    return True


# ---------------------------------------------------------------------------
# Graph metadata helpers
# ---------------------------------------------------------------------------

def graph_hash(graph_path: str) -> str | None:
    """Return sha256 hash of the graph file, or *None* if it doesn't exist."""
    p = Path(graph_path)
    if not p.exists():
        return None
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def graph_mtime(graph_path: str) -> str | None:
    """Return ISO-formatted mtime of the graph file, or *None*."""
    p = Path(graph_path)
    if not p.exists():
        return None
    from datetime import datetime, timezone
    mtime = p.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def make_graph_query_fn(
    graph_path: str,
    timeout: int = DEFAULT_TIMEOUT,
):
    """Return a callable ``(anchor: str) -> str`` suitable for MergeEngine."""
    def _query(anchor: str) -> str:
        return query_node_confidence(graph_path, anchor, timeout=timeout)
    return _query
