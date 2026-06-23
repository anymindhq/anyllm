"""Confidence-aware snapshot merging engine.

Classifies decisions from old and new snapshots into CONFIRMED, ADDED, STALE,
ORPHANED, or UPDATED states using codebase graph confidence when available.
"""
from __future__ import annotations

import hashlib
import re
import string
from dataclasses import dataclass, field
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    id: str                           # stable hash of normalized decision text
    text: str                         # human-readable decision
    code_anchor: str | None = None    # file path or symbol the decision refers to
    confidence: str = "UNKNOWN"       # EXTRACTED | INFERRED | AMBIGUOUS | UNKNOWN
    session_id: str = ""              # which session introduced this decision
    sessions_confirmed: list[str] = field(default_factory=list)
    sessions_absent: int = 0         # consecutive sessions where decision was absent


@dataclass
class MergeResult:
    confirmed: list[Decision]    # carried forward with high confidence
    updated: list[Decision]      # superseded by new decision (old version archived)
    added: list[Decision]        # new this session
    stale: list[Decision]        # graph says uncertain, needs human check
    orphaned: list[Decision]     # code anchor gone, archived with note
    merged_md: str               # the final current.md content


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    t = _STRIP_RE.sub("", text.lower())
    return _WHITESPACE_RE.sub(" ", t).strip()


def _bigrams(text: str) -> set[str]:
    """Return character-level bigrams of *normalised* text."""
    n = _normalise(text)
    if len(n) < 2:
        return set()
    return {n[i : i + 2] for i in range(len(n) - 1)}


def bigram_similarity(a: str, b: str) -> float:
    """Jaccard similarity over character bigrams of normalised text."""
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def decision_id(text: str) -> str:
    """Stable hash of a normalised decision string."""
    return hashlib.sha256(_normalise(text).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Code-anchor extraction
# ---------------------------------------------------------------------------

# Matches backtick-quoted identifiers like `auth.py`, `validate_jwt()`, `CacheManager`
_BACKTICK_RE = re.compile(r"`([^`]+)`")
# Matches file paths like src/auth.py, ./config.py, auth/middleware.py
_FILEPATH_RE = re.compile(
    r"(?:^|[\s(])("
    r"(?:\.{0,2}/)?(?:[\w\-]+/)*[\w\-]+\.(?:py|js|ts|go|rs|java|rb|c|cpp|h|hpp|yaml|yml|json|toml|md)"
    r")",
)


def extract_code_anchor(text: str) -> str | None:
    """Heuristically extract a code anchor from decision text.

    Prefers backtick-quoted file paths, then backtick-quoted symbols, then
    bare file paths in the text.
    """
    backtick_matches = _BACKTICK_RE.findall(text)
    for m in backtick_matches:
        # File path inside backticks
        if "." in m and "/" in m:
            return m.strip()
        if m.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".rb")):
            return m.strip()
    # Backtick-quoted symbol (function, class, etc.)
    for m in backtick_matches:
        cleaned = m.strip().rstrip("()")
        if cleaned and len(cleaned) > 1:
            return cleaned
    # Bare file path in text
    fp_matches = _FILEPATH_RE.findall(text)
    if fp_matches:
        return fp_matches[0].strip()
    return None


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

def _split_sections(md: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Split markdown into frontmatter dict and {section_name: content} map.

    Handles both `# Heading` and `## Heading` styles.
    """
    frontmatter: dict[str, Any] = {}
    body = md

    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", md, re.DOTALL)
    if m:
        try:
            frontmatter = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            frontmatter = {}
        body = m.group(2)

    sections: dict[str, str] = {}
    current_name: str | None = None
    buffer: list[str] = []
    for line in body.splitlines():
        hmatch = re.match(r"^#{1,2}\s+(.+?)\s*$", line)
        if hmatch:
            if current_name is not None:
                sections[current_name] = "\n".join(buffer).strip()
            current_name = hmatch.group(1).strip()
            buffer = []
        else:
            if current_name is not None:
                buffer.append(line)
    if current_name is not None:
        sections[current_name] = "\n".join(buffer).strip()

    return frontmatter, sections


def parse_decisions(md: str) -> list[Decision]:
    """Extract decisions from the `## Decisions` section of a snapshot.

    Each top-level bullet is one decision.  Sub-bullets are folded into the
    parent.  Lines tagged with ``[CONFIRMED | ...]`` or ``[NEW]`` have those
    tags stripped for normalisation but preserved in the raw text.
    """
    _, sections = _split_sections(md)
    dec_text = sections.get("Decisions", "")
    if not dec_text:
        return []

    decisions: list[Decision] = []
    current_lines: list[str] = []

    def _flush():
        if not current_lines:
            return
        raw = "\n".join(current_lines).strip()
        if not raw:
            return
        # Strip leading merge-tags for normalisation, keep in text
        cleaned = re.sub(
            r"^\[(?:CONFIRMED|NEW|STALE|ORPHANED|SUPERSEDED)[^\]]*\]\s*",
            "",
            raw,
        )
        anchor = extract_code_anchor(cleaned)
        decisions.append(Decision(
            id=decision_id(cleaned),
            text=raw,
            code_anchor=anchor,
        ))

    for line in dec_text.splitlines():
        stripped = line.strip()
        # Skip HTML comments
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        if stripped.startswith("<!--"):
            continue
        if stripped.endswith("-->"):
            continue
        # Top-level bullet starts a new decision
        if re.match(r"^- ", line.lstrip()) and not re.match(r"^\s{2,}- ", line):
            _flush()
            current_lines = [stripped.lstrip("- ").strip()]
        elif stripped:
            current_lines.append(stripped)
    _flush()
    return decisions


def _parse_section_list(section_text: str) -> list[str]:
    """Parse a markdown bullet list section into individual items."""
    items: list[str] = []
    current_lines: list[str] = []

    def _flush():
        if current_lines:
            items.append("\n".join(current_lines).strip())

    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("<!--") or stripped.endswith("-->"):
            continue
        if re.match(r"^- ", line.lstrip()) and not re.match(r"^\s{2,}- ", line):
            _flush()
            current_lines = [stripped.lstrip("- ").strip()]
        elif stripped:
            current_lines.append(stripped)
    _flush()
    return items


# ---------------------------------------------------------------------------
# Decision matching
# ---------------------------------------------------------------------------

# Thresholds for bigram-similarity matching
_ANCHOR_MATCH_THRESHOLD = 0.40   # lower bar when code anchors match
_TEXT_MATCH_THRESHOLD = 0.55     # higher bar when no anchor


def match_decisions(
    old: list[Decision], new: list[Decision]
) -> tuple[
    list[tuple[Decision, Decision]],   # matched pairs (old, new)
    list[Decision],                     # unmatched old
    list[Decision],                     # unmatched new
]:
    """Match decisions from old snapshot to new snapshot.

    Uses code_anchor + bigram similarity.  Returns matched pairs, unmatched
    old decisions (dropped/absent), and unmatched new decisions (added).
    """
    used_new: set[int] = set()
    matched: list[tuple[Decision, Decision]] = []
    unmatched_old: list[Decision] = []

    for od in old:
        best_idx: int | None = None
        best_sim = 0.0
        threshold = _TEXT_MATCH_THRESHOLD

        for i, nd in enumerate(new):
            if i in used_new:
                continue
            # Anchor match lowers the threshold
            if od.code_anchor and nd.code_anchor and od.code_anchor == nd.code_anchor:
                sim = bigram_similarity(od.text, nd.text)
                if sim > _ANCHOR_MATCH_THRESHOLD and sim > best_sim:
                    best_sim = sim
                    best_idx = i
                    threshold = _ANCHOR_MATCH_THRESHOLD
            else:
                sim = bigram_similarity(od.text, nd.text)
                if sim > _TEXT_MATCH_THRESHOLD and sim > best_sim:
                    best_sim = sim
                    best_idx = i

        if best_idx is not None:
            used_new.add(best_idx)
            matched.append((od, new[best_idx]))
        else:
            unmatched_old.append(od)

    unmatched_new = [nd for i, nd in enumerate(new) if i not in used_new]
    return matched, unmatched_old, unmatched_new


# ---------------------------------------------------------------------------
# Merge engine
# ---------------------------------------------------------------------------

class MergeEngine:
    """Three-state decision classification and merged Markdown rendering."""

    def __init__(
        self,
        stale_threshold: int = 3,
        graph_query_fn: Any = None,
    ):
        self.stale_threshold = stale_threshold
        # graph_query_fn(anchor: str) -> str  — returns EXTRACTED|INFERRED|AMBIGUOUS|MISSING
        self._graph_query = graph_query_fn

    def merge(
        self,
        prev_md: str,
        new_md: str,
        *,
        session_id: str = "",
        graph_path: str | None = None,
    ) -> MergeResult:
        """Merge previous current.md with a new snapshot.

        Implements the decision state machine from the PRD.
        """
        prev_fm, prev_sections = _split_sections(prev_md)
        new_fm, new_sections = _split_sections(new_md)

        # Parse decisions from both
        old_decisions = parse_decisions(prev_md)
        new_decisions = parse_decisions(new_md)

        # Restore accumulated state from previous decisions
        self._restore_decision_state(old_decisions, prev_fm)

        # Match old decisions to new ones
        matched, absent_old, added_new = match_decisions(old_decisions, new_decisions)

        confirmed: list[Decision] = []
        updated: list[Decision] = []
        added: list[Decision] = []
        stale: list[Decision] = []
        orphaned: list[Decision] = []

        # --- Matched decisions: CONFIRMED (update wording to latest) ---
        for old_d, new_d in matched:
            d = Decision(
                id=decision_id(new_d.text),
                text=new_d.text,
                code_anchor=new_d.code_anchor or old_d.code_anchor,
                confidence=old_d.confidence if old_d.confidence != "UNKNOWN" else "UNKNOWN",
                session_id=old_d.session_id or session_id,
                sessions_confirmed=list(old_d.sessions_confirmed),
                sessions_absent=0,  # reset: it appeared
            )
            if session_id and session_id not in d.sessions_confirmed:
                d.sessions_confirmed.append(session_id)
            # If wording changed significantly, track as UPDATED
            if bigram_similarity(old_d.text, new_d.text) < 0.85:
                updated.append(old_d)  # old version → superseded
            confirmed.append(d)

        # --- Absent old decisions: query graph or mark stale ---
        for old_d in absent_old:
            old_d.sessions_absent += 1
            graph_confidence = self._query_graph(old_d.code_anchor, graph_path)
            if graph_confidence:
                old_d.confidence = graph_confidence

            if graph_confidence == "EXTRACTED":
                # Pinned by graph — confirmed even though absent from new snapshot
                old_d.sessions_absent = 0
                if session_id and session_id not in old_d.sessions_confirmed:
                    old_d.sessions_confirmed.append(session_id)
                confirmed.append(old_d)
            elif graph_confidence == "INFERRED":
                stale.append(old_d)
            elif graph_confidence in ("AMBIGUOUS", "MISSING"):
                if old_d.sessions_absent >= self.stale_threshold:
                    orphaned.append(old_d)
                else:
                    stale.append(old_d)
            else:
                # No graph available — conservative fallback: STALE
                if old_d.sessions_absent >= self.stale_threshold:
                    orphaned.append(old_d)
                else:
                    stale.append(old_d)

        # --- New decisions: ADDED ---
        for new_d in added_new:
            d = Decision(
                id=decision_id(new_d.text),
                text=new_d.text,
                code_anchor=new_d.code_anchor,
                confidence="UNKNOWN",
                session_id=session_id,
                sessions_confirmed=[session_id] if session_id else [],
                sessions_absent=0,
            )
            added.append(d)

        # Merge other sections
        merged_md = self._render(
            prev_fm=prev_fm,
            new_fm=new_fm,
            prev_sections=prev_sections,
            new_sections=new_sections,
            confirmed=confirmed,
            updated=updated,
            added=added,
            stale=stale,
            orphaned=orphaned,
            session_id=session_id,
            graph_path=graph_path,
        )

        return MergeResult(
            confirmed=confirmed,
            updated=updated,
            added=added,
            stale=stale,
            orphaned=orphaned,
            merged_md=merged_md,
        )

    def _restore_decision_state(
        self, decisions: list[Decision], frontmatter: dict[str, Any]
    ) -> None:
        """Restore accumulated state (session provenance, absence count) from frontmatter."""
        provenance = frontmatter.get("decision_provenance") or {}
        for d in decisions:
            key = d.code_anchor or d.id
            if key in provenance:
                info = provenance[key]
                d.session_id = info.get("introduced", d.session_id)
                d.sessions_confirmed = list(info.get("confirmed_in", []))
                d.sessions_absent = int(info.get("sessions_absent", 0))
                d.confidence = info.get("confidence", d.confidence)

    def _query_graph(self, anchor: str | None, graph_path: str | None) -> str | None:
        """Query the graph for a code anchor's confidence."""
        if not anchor or not self._graph_query:
            return None
        try:
            return self._graph_query(anchor)
        except Exception:
            return None

    def _render(
        self,
        *,
        prev_fm: dict[str, Any],
        new_fm: dict[str, Any],
        prev_sections: dict[str, str],
        new_sections: dict[str, str],
        confirmed: list[Decision],
        updated: list[Decision],
        added: list[Decision],
        stale: list[Decision],
        orphaned: list[Decision],
        session_id: str,
        graph_path: str | None,
    ) -> str:
        """Render the merged current.md with the new section layout."""
        # --- Frontmatter ---
        merged_from = list(prev_fm.get("merged_from") or [])
        if session_id and session_id not in merged_from:
            merged_from.append(session_id)

        confidence_report = {
            "confirmed": len(confirmed),
            "added": len(added),
            "stale": len(stale),
            "orphaned": len(orphaned),
        }

        # Build decision provenance for frontmatter
        decision_provenance: dict[str, Any] = {}
        for d in confirmed + added + stale:
            key = d.code_anchor or d.id
            decision_provenance[key] = {
                "introduced": d.session_id,
                "confirmed_in": d.sessions_confirmed,
                "sessions_absent": d.sessions_absent,
                "confidence": d.confidence,
            }

        fm = dict(new_fm)  # Start from new snapshot's frontmatter
        fm["merged_from"] = merged_from
        fm["confidence_report"] = confidence_report
        fm["decision_provenance"] = decision_provenance
        if graph_path:
            fm["graph_version"] = graph_path

        fm_yaml = yaml.safe_dump(fm, sort_keys=False).rstrip()
        parts = [f"---\n{fm_yaml}\n---\n"]

        # --- Task (from latest snapshot) ---
        task = new_sections.get("Task", prev_sections.get("Task", ""))
        if task:
            parts.append(f"## Task\n{task}\n")

        # --- Status (from latest snapshot) ---
        status = new_sections.get("Status", prev_sections.get("Status", ""))
        if status:
            parts.append(f"## Status\n{status}\n")

        # --- Decisions (merged) ---
        dec_lines = ["## Decisions"]
        if confirmed:
            dec_lines.append("<!-- CONFIRMED: verified by graph or re-stated in latest session -->")
            for d in confirmed:
                anchor_tag = f" | {d.code_anchor}" if d.code_anchor else ""
                dec_lines.append(f"- [CONFIRMED{anchor_tag}] {self._clean_decision_text(d.text)}")
        if added:
            dec_lines.append("")
            dec_lines.append("<!-- ADDED: new this session -->")
            for d in added:
                dec_lines.append(f"- [NEW] {self._clean_decision_text(d.text)}")
        parts.append("\n".join(dec_lines) + "\n")

        # --- Superseded Decisions ---
        if updated:
            sup_lines = [
                "## Superseded Decisions",
                "<!-- Decisions replaced this session. Preserved so the next model knows what NOT to try. -->",
            ]
            for d in updated:
                sup_lines.append(
                    f"- [SUPERSEDED] {self._clean_decision_text(d.text)}"
                )
            parts.append("\n".join(sup_lines) + "\n")

        # --- Code Map (from latest snapshot) ---
        code_map = new_sections.get("Code map", new_sections.get("Code Map", ""))
        if not code_map:
            code_map = prev_sections.get("Code map", prev_sections.get("Code Map", ""))
        if code_map:
            parts.append(f"## Code Map\n{code_map}\n")

        # --- Failed Approaches (union of all sessions — never dropped) ---
        prev_failed = prev_sections.get("Tried & failed", prev_sections.get("Failed Approaches", ""))
        new_failed = new_sections.get("Tried & failed", new_sections.get("Failed Approaches", ""))
        merged_failed = self._merge_list_sections(prev_failed, new_failed)
        if merged_failed:
            parts.append(f"## Failed Approaches\n{merged_failed}\n")

        # --- Next Step (from latest snapshot) ---
        next_step = new_sections.get("Next step", new_sections.get("Next Step", ""))
        if not next_step:
            next_step = prev_sections.get("Next step", prev_sections.get("Next Step", ""))
        if next_step:
            parts.append(f"## Next Step\n{next_step}\n")

        # --- Open Questions (merged — carried forward until resolved) ---
        prev_questions = prev_sections.get("Open questions", prev_sections.get("Open Questions", ""))
        new_questions = new_sections.get("Open questions", new_sections.get("Open Questions", ""))
        merged_questions = self._merge_list_sections(prev_questions, new_questions)
        if merged_questions:
            parts.append(f"## Open Questions\n{merged_questions}\n")

        # --- Stale / Needs Verification ---
        if stale:
            stale_lines = [
                "## Stale / Needs Verification",
                "<!-- graphify confidence = INFERRED or AMBIGUOUS. Human or next model should verify. -->",
            ]
            for d in stale:
                conf_tag = f" | confidence: {d.confidence}" if d.confidence != "UNKNOWN" else ""
                stale_lines.append(
                    f"- [STALE{conf_tag}] {self._clean_decision_text(d.text)}"
                )
            parts.append("\n".join(stale_lines) + "\n")

        # --- Session Provenance table ---
        all_tracked = confirmed + added + stale
        if all_tracked:
            prov_lines = [
                "## Session Provenance",
                "<!-- Which session introduced which decision -->",
                "| Decision anchor | Introduced | Last confirmed |",
                "|---|---|---|",
            ]
            for d in all_tracked:
                anchor = d.code_anchor or d.id[:8]
                introduced = d.session_id or "unknown"
                last_confirmed = d.sessions_confirmed[-1] if d.sessions_confirmed else introduced
                prov_lines.append(f"| {anchor} | {introduced} | {last_confirmed} |")
            parts.append("\n".join(prov_lines) + "\n")

        # --- Confidence Report ---
        cr = new_sections.get("Confidence Report", "")
        if cr:
            parts.append(f"## Confidence Report\n{cr}\n")

        return "\n".join(parts)

    @staticmethod
    def _clean_decision_text(text: str) -> str:
        """Remove existing merge tags from decision text for re-tagging."""
        return re.sub(
            r"^\[(?:CONFIRMED|NEW|STALE|ORPHANED|SUPERSEDED)[^\]]*\]\s*",
            "",
            text,
        ).strip()

    @staticmethod
    def _merge_list_sections(prev: str, new: str) -> str:
        """Union two bullet-list sections, deduplicating by normalised text."""
        prev_items = _parse_section_list(prev) if prev else []
        new_items = _parse_section_list(new) if new else []

        seen: set[str] = set()
        merged: list[str] = []
        for item in prev_items + new_items:
            norm = _normalise(item)
            if norm not in seen:
                seen.add(norm)
                merged.append(f"- {item}")

        return "\n".join(merged)
