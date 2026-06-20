"""Graph context enrichment for agent briefings.

When ``anyllm prime`` hands off context to another agent, the briefing today
is just a flat markdown file — decisions and status as prose.  This module
queries graphify's knowledge graph to inject *structural* codebase context:

- Which modules depend on which
- What functions/classes exist at the code anchors referenced in decisions
- How the codebase is actually connected

The enriched briefing lets the receiving agent understand the project
architecture, not just what was *said* about it.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Graph summary extraction
# ---------------------------------------------------------------------------

def extract_graph_summary(graph_path: str, *, max_nodes: int = 50) -> dict[str, Any] | None:
    """Read the graphify graph JSON and extract a structural summary.

    Returns a dict with ``modules``, ``key_symbols``, and ``dependencies``,
    or *None* if the graph file doesn't exist or can't be parsed.
    """
    p = Path(graph_path)
    if not p.exists():
        return None

    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read graph at %s: %s", graph_path, exc)
        return None

    nodes = data.get("nodes", [])
    edges = data.get("edges", data.get("relationships", []))

    # Collect modules (files) and key symbols (functions, classes)
    modules: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []

    for node in nodes[:max_nodes * 3]:  # scan broadly, trim later
        ntype = node.get("type", "").lower()
        if ntype in ("file", "module"):
            modules.append({
                "name": node.get("name", ""),
                "path": node.get("file", node.get("path", "")),
                "confidence": node.get("confidence", "UNKNOWN"),
            })
        elif ntype in ("function", "class", "method"):
            symbols.append({
                "name": node.get("name", ""),
                "type": ntype,
                "file": node.get("file", ""),
                "confidence": node.get("confidence", "UNKNOWN"),
            })

    # Collect dependency edges
    dependencies: list[dict[str, str]] = []
    for edge in edges[:max_nodes * 2]:
        dependencies.append({
            "from": edge.get("source", edge.get("from", "")),
            "to": edge.get("target", edge.get("to", "")),
            "type": edge.get("type", edge.get("relationship", "depends_on")),
        })

    return {
        "modules": modules[:max_nodes],
        "key_symbols": symbols[:max_nodes],
        "dependencies": dependencies[:max_nodes],
        "total_nodes": len(nodes),
        "total_edges": len(edges),
    }


def query_anchors_context(
    graph_path: str,
    anchors: list[str],
    *,
    timeout: int = 30,
) -> dict[str, dict[str, Any]]:
    """Query graphify for detailed context on specific code anchors.

    For each anchor referenced in decisions, fetch its neighbors —
    what calls it, what it calls, what module it lives in.

    Returns ``{anchor: {exists, confidence, neighbors, file, type}}``.
    """
    from .graph_bridge import graphify_available

    results: dict[str, dict[str, Any]] = {}

    if not graphify_available():
        return results

    for anchor in anchors:
        try:
            proc = subprocess.run(
                ["graphify", "query", anchor, "--graph", graph_path, "--json"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                results[anchor] = {
                    "exists": data.get("exists", False),
                    "confidence": data.get("confidence", "MISSING"),
                    "type": data.get("node_type", "unknown"),
                    "file": data.get("file", ""),
                    "neighbors": data.get("neighbors", []),
                }
            else:
                results[anchor] = {"exists": False, "confidence": "MISSING"}
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as exc:
            logger.debug("Failed to query anchor %r: %s", anchor, exc)
            results[anchor] = {"exists": False, "confidence": "MISSING"}

    return results


# ---------------------------------------------------------------------------
# Briefing enrichment
# ---------------------------------------------------------------------------

def render_graph_context(
    graph_summary: dict[str, Any] | None,
    anchor_context: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Render graph context as markdown sections for the briefing.

    This is injected into the briefing between the Code Map and Decisions
    sections so the receiving agent has structural awareness.
    """
    if not graph_summary:
        return ""

    parts: list[str] = []

    # --- Architecture overview ---
    total_nodes = graph_summary.get("total_nodes", 0)
    total_edges = graph_summary.get("total_edges", 0)
    parts.append("## Codebase Structure (from graph)")
    parts.append(f"*{total_nodes} nodes, {total_edges} relationships extracted from source code.*")
    parts.append("")

    # --- Module listing ---
    modules = graph_summary.get("modules", [])
    if modules:
        parts.append("### Modules")
        for mod in modules:
            conf = mod.get("confidence", "")
            conf_tag = f" [{conf}]" if conf and conf != "UNKNOWN" else ""
            path = mod.get("path") or mod.get("name", "?")
            parts.append(f"- `{path}`{conf_tag}")
        parts.append("")

    # --- Key symbols ---
    symbols = graph_summary.get("key_symbols", [])
    if symbols:
        parts.append("### Key Functions & Classes")
        for sym in symbols[:30]:  # cap for briefing size
            stype = sym.get("type", "")
            sfile = sym.get("file", "")
            loc = f" in `{sfile}`" if sfile else ""
            parts.append(f"- `{sym['name']}` ({stype}){loc}")
        parts.append("")

    # --- Dependencies ---
    deps = graph_summary.get("dependencies", [])
    if deps:
        parts.append("### Dependencies")
        for dep in deps[:20]:  # cap for briefing size
            parts.append(f"- `{dep['from']}` → `{dep['to']}` ({dep.get('type', 'depends_on')})")
        parts.append("")

    # --- Anchor-specific context ---
    if anchor_context:
        verified = {k: v for k, v in anchor_context.items() if v.get("exists")}
        if verified:
            parts.append("### Decision Anchors (verified against code)")
            for anchor, info in verified.items():
                conf = info.get("confidence", "UNKNOWN")
                atype = info.get("type", "unknown")
                afile = info.get("file", "")
                loc = f" in `{afile}`" if afile else ""
                neighbors = info.get("neighbors", [])
                parts.append(f"- **`{anchor}`** — {atype}{loc} [{conf}]")
                if neighbors:
                    for n in neighbors[:5]:
                        nname = n if isinstance(n, str) else n.get("name", "?")
                        parts.append(f"  - connected to `{nname}`")
            parts.append("")

    return "\n".join(parts)


def enrich_briefing(
    briefing: dict[str, Any],
    graph_path: str | None,
    *,
    timeout: int = 30,
) -> dict[str, Any]:
    """Enrich a composed briefing with graphify structural context.

    Called between ``compose()`` and ``adapter.render()`` in the prime flow.
    Adds a ``graph_context`` key to the briefing sections and enriches
    the verification hooks.

    If no graph is available, returns the briefing unchanged.
    """
    if not graph_path:
        return briefing

    # Extract graph summary
    summary = extract_graph_summary(graph_path)
    if not summary:
        return briefing

    # Collect code anchors from decisions
    decisions_text = briefing.get("sections", {}).get("Decisions", "")
    from .merger import parse_decisions, extract_code_anchor
    anchors = []
    if decisions_text:
        # Build a minimal markdown to parse
        md = f"## Decisions\n{decisions_text}"
        decisions = parse_decisions(md)
        anchors = [d.code_anchor for d in decisions if d.code_anchor]

    # Query anchor context
    anchor_ctx = query_anchors_context(graph_path, anchors, timeout=timeout) if anchors else None

    # Render and inject
    graph_md = render_graph_context(summary, anchor_ctx)
    if graph_md:
        sections = dict(briefing.get("sections", {}))
        sections["Codebase Structure"] = graph_md
        briefing = {**briefing, "sections": sections}

        # Add verification hook
        hooks = list(briefing.get("verification_hooks", []))
        hooks.append(
            "The Codebase Structure section was extracted from the actual source code "
            "via AST analysis. Use it to understand module boundaries and call relationships."
        )
        briefing = {**briefing, "verification_hooks": hooks}

    return briefing
