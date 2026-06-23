from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml


SECTION_ORDER = [
    "Task",
    "Status",
    "Decisions",
    "Superseded Decisions",
    "Code map",
    "Code Map",
    "Failed Approaches",
    "Tried & failed",
    "Next step",
    "Next Step",
    "Open questions",
    "Open Questions",
    "Stale / Needs Verification",
    "Session Provenance",
    "Confidence Report",
]


@dataclass
class Snapshot:
    frontmatter: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, str] = field(default_factory=dict)

    def get(self, name: str) -> str:
        return self.sections.get(name, "").strip()


def parse_snapshot(md: str) -> Snapshot:
    """Parse a snapshot markdown document (with YAML frontmatter) into sections."""
    frontmatter: dict[str, Any] = {}
    body = md
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", md, re.DOTALL)
    if m:
        try:
            frontmatter = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            frontmatter = {}
        body = m.group(2)

    sections: dict[str, str] = {}
    # Split on `# Heading` lines (top-level only).
    current_name: str | None = None
    buffer: list[str] = []
    for line in body.splitlines():
        hmatch = re.match(r"^#\s+(.+?)\s*$", line)
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

    return Snapshot(frontmatter=frontmatter, sections=sections)


def _low_confidence_sections(confidence_report: str) -> list[str]:
    """Pull section names listed as low confidence from the Confidence Report."""
    if not confidence_report:
        return []
    for line in confidence_report.splitlines():
        low = line.strip().lower()
        if low.startswith("- low confidence:") or low.startswith("low confidence:"):
            _, _, rest = line.partition(":")
            rest = rest.strip()
            if not rest or rest.lower() in {"none", "(none)", "n/a"}:
                return []
            return [s.strip() for s in rest.split(",") if s.strip()]
    return []


def compose(
    snapshot: Snapshot,
    *,
    target: str,
    extra_rules: list[str] | None = None,
    tone: str = "direct",
) -> dict[str, Any]:
    """Turn a parsed snapshot into an adapter-agnostic briefing JSON.

    This is the "instructional framing" stage from section 5.2D of the spec.
    """
    confidence_report = snapshot.get("Confidence Report")
    low_conf = _low_confidence_sections(confidence_report)

    role_preamble = (
        "You are continuing an existing coding task that a previous LLM "
        "session was in the middle of. The developer hit a wall in that "
        "session (context limit, credits, provider outage, or wanting a "
        "second opinion) and has moved to you. Below is a distilled briefing "
        "of that session. Use it — do not discard it."
    )

    anti_repetition = [
        "Do NOT restart the task from scratch.",
        "Do NOT re-implement parts that the Status or Code map marks as done.",
        "Do NOT re-ask the user questions that the Decisions or Status already answer.",
        "Do NOT retry any approach listed under \"Tried & failed\" without a new reason.",
        "When in doubt between a prior Decision and your own instinct, respect the Decision or ask.",
    ]

    verification_hooks: list[str] = []
    if low_conf:
        verification_hooks.append(
            "The following sections are marked LOW CONFIDENCE by the distiller — "
            "verify against the actual code before relying on them: "
            + ", ".join(low_conf) + "."
        )
    verification_hooks.append(
        "If the Code map references a file that doesn't exist, stop and flag it "
        "to the user rather than guessing."
    )

    briefing: dict[str, Any] = {
        "target": target,
        "tone": tone,
        "frontmatter": snapshot.frontmatter,
        "role_preamble": role_preamble,
        "anti_repetition": anti_repetition,
        "verification_hooks": verification_hooks,
        "extra_rules": list(extra_rules or []),
        "sections": {name: snapshot.get(name) for name in SECTION_ORDER},
        "low_confidence_sections": low_conf,
    }
    return briefing
