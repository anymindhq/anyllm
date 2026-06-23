from .base import Ingestor, NormalizedTranscript
from .claude_code import ClaudeCodeIngestor

INGESTORS: dict[str, type[Ingestor]] = {
    "claude-code": ClaudeCodeIngestor,
}

__all__ = ["Ingestor", "NormalizedTranscript", "ClaudeCodeIngestor", "INGESTORS"]
