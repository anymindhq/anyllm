from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]


PROMPT_VERSION = "v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"


class DistillerError(RuntimeError):
    pass


def _load_prompt() -> str:
    return PROMPT_PATH.read_text()


def _turns_to_text(turns: list[dict[str, Any]], max_chars: int = 180_000) -> str:
    """Render turns as plain text for the distiller, with a soft cap."""
    lines: list[str] = []
    total = 0
    for t in turns:
        role = t.get("role", "?").upper()
        text = (t.get("text") or "").strip()
        tool_calls = t.get("tool_calls") or []
        block = f"[{role} @ {t.get('ts','')}]"
        if text:
            block += f"\n{text}"
        if tool_calls:
            tool_summary = "; ".join(
                f"{tc.get('name')}({_short_input(tc.get('input'))})" for tc in tool_calls
            )
            block += f"\n<tool_calls>{tool_summary}</tool_calls>"
        lines.append(block)
        total += len(block)
        if total > max_chars:
            lines.append(f"\n[...truncated {len(turns) - len(lines)} more turns...]")
            break
    return "\n\n".join(lines)


def _short_input(inp: Any, limit: int = 160) -> str:
    if inp is None:
        return ""
    try:
        s = json.dumps(inp, ensure_ascii=False)
    except TypeError:
        s = str(inp)
    return s if len(s) <= limit else s[: limit - 1] + "…"


class Distiller:
    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        budget_tokens: int = 2000,
        api_key: str | None = None,
    ):
        self.model = model
        self.budget_tokens = budget_tokens
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._prompt = _load_prompt()

    def distill(self, transcript: dict[str, Any], project: str) -> str:
        """Return a markdown snapshot for the given normalized transcript."""
        frontmatter = self._frontmatter(transcript, project)
        user_msg = self._user_message(transcript, project, frontmatter)

        if not self.api_key or anthropic is None:
            # Offline fallback: produce a minimal hand-skeleton snapshot so the
            # pipeline still completes. Flagged as low-confidence everywhere.
            return self._offline_snapshot(frontmatter, transcript)

        client = anthropic.Anthropic(api_key=self.api_key)
        # Allow a generous output budget; the prompt itself asks the model to
        # stay inside `budget_tokens` for the final primer.
        max_output = max(self.budget_tokens * 2, 1500)
        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=max_output,
                system=self._prompt,
                messages=[{"role": "user", "content": user_msg}],
            )
        except Exception as e:  # surface the real cause
            raise DistillerError(f"Anthropic API call failed: {e}") from e

        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        ).strip()

        if not text.startswith("---"):
            # Model ignored format: splice our frontmatter on top.
            text = self._wrap_frontmatter(frontmatter, text)
        return text

    def _frontmatter(self, transcript: dict[str, Any], project: str) -> dict[str, Any]:
        md = transcript.get("metadata") or {}
        return {
            "anyllm_version": "0.1",
            "project": project,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "distilled_from": [{
                "source": transcript.get("source"),
                "session_id": transcript.get("session_id"),
                "turn_count": len(transcript.get("turns") or []),
                "token_count": md.get("token_count", 0),
            }],
            "budget_tokens": self.budget_tokens,
            "distiller_model": self.model,
            "prompt_version": PROMPT_VERSION,
        }

    def _user_message(
        self, transcript: dict[str, Any], project: str, frontmatter: dict[str, Any]
    ) -> str:
        md = transcript.get("metadata") or {}
        header = (
            f"Project: {project}\n"
            f"Source: {transcript.get('source')}\n"
            f"Session: {transcript.get('session_id')}\n"
            f"Model: {md.get('model')}\n"
            f"Token budget for snapshot: {self.budget_tokens} tokens\n"
            f"Files touched (from tool calls): {', '.join(transcript.get('files_touched') or []) or 'none observed'}\n"
        )
        fm_yaml = _yaml_frontmatter(frontmatter)
        turns = _turns_to_text(transcript.get("turns") or [])
        return (
            f"{header}\n"
            f"Use EXACTLY this frontmatter block at the top of your output:\n\n"
            f"{fm_yaml}\n"
            f"--- TRANSCRIPT BEGINS ---\n\n"
            f"{turns}\n\n"
            f"--- TRANSCRIPT ENDS ---\n"
        )

    def _wrap_frontmatter(self, frontmatter: dict[str, Any], body: str) -> str:
        return f"{_yaml_frontmatter(frontmatter)}\n{body}\n"

    def _offline_snapshot(self, frontmatter: dict[str, Any], transcript: dict[str, Any]) -> str:
        files = transcript.get("files_touched") or []
        code_map = "\n".join(f"- `{fp}` — touched during session" for fp in files) or "- (none)"
        body = (
            "# Task\n"
            "Unknown — distiller ran offline (no ANTHROPIC_API_KEY).\n\n"
            "# Status\n"
            "Transcript captured but not distilled. Run `anyllm pack` again with "
            "`ANTHROPIC_API_KEY` set to generate a real briefing.\n\n"
            "# Decisions\n- (none extracted). _conf: low_\n\n"
            f"# Code map\n{code_map}\n\n"
            "# Tried & failed\n- (unknown without distillation)\n\n"
            "# Next step\nSet ANTHROPIC_API_KEY and re-run `anyllm pack`.\n\n"
            "# Open questions\n- (none)\n\n"
            "# Confidence Report\n"
            "- Overall: low\n"
            "- High confidence: none\n"
            "- Medium confidence: none\n"
            "- Low confidence: all sections (offline fallback)\n"
            "- Omitted (budget): entire transcript body\n"
            "- Could not determine: everything requiring semantic understanding\n"
        )
        return self._wrap_frontmatter(frontmatter, body)


def _yaml_frontmatter(data: dict[str, Any]) -> str:
    # We keep this hand-rolled to guarantee the key order in the snapshot.
    import yaml
    body = yaml.safe_dump(data, sort_keys=False).rstrip()
    return f"---\n{body}\n---"
