from __future__ import annotations

from typing import Any, Protocol


class Adapter(Protocol):
    name: str

    def render(self, briefing: dict[str, Any]) -> str:
        """Render the composed briefing into a target-specific primer string."""
        ...
