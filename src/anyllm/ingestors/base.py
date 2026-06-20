from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class NormalizedTranscript:
    source: str
    session_id: str
    started_at: str
    ended_at: str
    turns: list[dict[str, Any]] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "turns": self.turns,
            "files_touched": self.files_touched,
            "metadata": self.metadata,
        }


class Ingestor(Protocol):
    name: str

    def latest_session(self, project_root: Path) -> NormalizedTranscript | None:
        """Return the most recent normalized transcript for this project, if any."""
        ...
