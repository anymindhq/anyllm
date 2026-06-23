from __future__ import annotations

from typing import Any


class ChatGPTAdapter:
    """Render a briefing as a copy-pasteable markdown primer for ChatGPT.

    ChatGPT's quirks (per architecture §5.2E):
      - Prefers markdown with clear role framing.
      - Shorter, structured primers outperform long XML-ish blobs.
      - Explicit `## Your task` section at the end focuses the model.
    """

    name = "chatgpt"

    def render(self, briefing: dict[str, Any]) -> str:
        sections = briefing.get("sections", {})
        fm = briefing.get("frontmatter", {}) or {}
        project = fm.get("project", "this project")

        parts: list[str] = []
        parts.append(f"# Briefing: continuing work on `{project}`")
        parts.append("")
        parts.append(briefing["role_preamble"])
        parts.append("")

        parts.append("## Ground rules")
        for rule in briefing.get("anti_repetition", []):
            parts.append(f"- {rule}")
        for hook in briefing.get("verification_hooks", []):
            parts.append(f"- {hook}")
        for extra in briefing.get("extra_rules", []):
            parts.append(f"- {extra}")
        parts.append("")

        if sections.get("Task"):
            parts.append("## Task")
            parts.append(sections["Task"])
            parts.append("")

        if sections.get("Status"):
            parts.append("## Status so far")
            parts.append(sections["Status"])
            parts.append("")

        if sections.get("Decisions"):
            parts.append("## Decisions already made (respect these)")
            parts.append(sections["Decisions"])
            parts.append("")

        # Superseded decisions — so the agent knows what NOT to retry
        if sections.get("Superseded Decisions"):
            parts.append("## Superseded decisions (do not revert to these)")
            parts.append(sections["Superseded Decisions"])
            parts.append("")

        if sections.get("Code map") or sections.get("Code Map"):
            parts.append("## Code map")
            parts.append(sections.get("Code map") or sections.get("Code Map", ""))
            parts.append("")

        # Graph-enriched codebase structure
        if sections.get("Codebase Structure"):
            parts.append(sections["Codebase Structure"])
            parts.append("")

        if sections.get("Tried & failed") or sections.get("Failed Approaches"):
            parts.append("## Tried & failed (do not redo)")
            parts.append(sections.get("Tried & failed") or sections.get("Failed Approaches", ""))
            parts.append("")

        if sections.get("Open questions") or sections.get("Open Questions"):
            parts.append("## Open questions for the user")
            parts.append(sections.get("Open questions") or sections.get("Open Questions", ""))
            parts.append("")

        # Stale decisions — flag for verification
        if sections.get("Stale / Needs Verification"):
            parts.append("## Stale decisions (verify before relying on these)")
            parts.append(sections["Stale / Needs Verification"])
            parts.append("")

        if sections.get("Confidence Report"):
            parts.append("## Distiller confidence report")
            parts.append(sections["Confidence Report"])
            parts.append("")

        parts.append("## Your task right now")
        next_step = sections.get("Next step") or sections.get("Next Step") or "Pick up from the Status section."
        parts.append(next_step)
        parts.append("")
        parts.append(
            "Begin by confirming in one line which Decision or file you are touching "
            "first, then proceed. If anything in this briefing contradicts what you "
            "see in the code, stop and ask before changing course."
        )

        return "\n".join(parts).rstrip() + "\n"

