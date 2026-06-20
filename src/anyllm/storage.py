from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ANYLLM_DIRNAME = ".anyllm"


@dataclass
class Paths:
    root: Path

    @property
    def anyllm_dir(self) -> Path:
        return self.root / ANYLLM_DIRNAME

    @property
    def sessions_dir(self) -> Path:
        return self.anyllm_dir / "sessions"

    @property
    def index_path(self) -> Path:
        return self.anyllm_dir / "index.json"

    @property
    def current_path(self) -> Path:
        return self.anyllm_dir / "current.md"

    @property
    def config_path(self) -> Path:
        return self.anyllm_dir / "config.yaml"


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from `start` looking for a .anyllm directory. Fall back to cwd."""
    start = (start or Path.cwd()).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ANYLLM_DIRNAME).is_dir():
            return candidate
    return start


def ensure_initialized(paths: Paths) -> None:
    if not paths.anyllm_dir.is_dir():
        raise RuntimeError(
            f"No {ANYLLM_DIRNAME}/ directory found at {paths.root}. "
            "Run `anyllm init` first."
        )


def init_project(root: Path) -> Paths:
    paths = Paths(root=root.resolve())
    paths.anyllm_dir.mkdir(exist_ok=True)
    paths.sessions_dir.mkdir(exist_ok=True)
    if not paths.index_path.exists():
        paths.index_path.write_text(json.dumps({"sessions": []}, indent=2))
    return paths


def load_index(paths: Paths) -> dict[str, Any]:
    if not paths.index_path.exists():
        return {"sessions": []}
    return json.loads(paths.index_path.read_text())


def save_index(paths: Paths, index: dict[str, Any]) -> None:
    paths.index_path.write_text(json.dumps(index, indent=2))


def append_index_entry(paths: Paths, entry: dict[str, Any]) -> None:
    index = load_index(paths)
    # De-duplicate by session_id + source: replace prior entry if present.
    key = (entry.get("source"), entry.get("session_id"))
    index["sessions"] = [
        s for s in index.get("sessions", [])
        if (s.get("source"), s.get("session_id")) != key
    ]
    index["sessions"].append(entry)
    save_index(paths, index)


def session_basename(started_at: str, session_id: str) -> str:
    # started_at is ISO; take the date portion for filename readability.
    try:
        date = started_at[:10]
    except Exception:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{date}-{session_id}"


def write_transcript(paths: Paths, transcript: dict[str, Any]) -> Path:
    base = session_basename(transcript.get("started_at", ""), transcript["session_id"])
    path = paths.sessions_dir / f"{base}.transcript.json"
    path.write_text(json.dumps(transcript, indent=2))
    return path


def write_snapshot(paths: Paths, transcript: dict[str, Any], snapshot_md: str) -> Path:
    base = session_basename(transcript.get("started_at", ""), transcript["session_id"])
    path = paths.sessions_dir / f"{base}.snapshot.md"
    path.write_text(snapshot_md)
    return path


def write_current(paths: Paths, snapshot_md: str) -> Path:
    """Overwrite current.md with the raw snapshot (legacy clobber behavior)."""
    paths.current_path.write_text(snapshot_md)
    return paths.current_path


def write_merged_current(
    paths: Paths,
    snapshot_md: str,
    *,
    session_id: str = "",
    graph_path: str | None = None,
    stale_threshold: int = 3,
    graph_query_fn: Any = None,
) -> tuple[Path, Any]:
    """Merge new snapshot into existing current.md and write the result.

    If no previous current.md exists, the snapshot is written directly
    (equivalent to the first session).  Returns ``(path, merge_result)``.
    The ``merge_result`` is *None* when no merge was performed.
    """
    from .merger import MergeEngine  # deferred to avoid circular imports

    if not paths.current_path.exists():
        # First session: no merge needed.
        paths.current_path.write_text(snapshot_md)
        return paths.current_path, None

    prev_md = paths.current_path.read_text()

    engine = MergeEngine(
        stale_threshold=stale_threshold,
        graph_query_fn=graph_query_fn,
    )

    try:
        result = engine.merge(
            prev_md,
            snapshot_md,
            session_id=session_id,
            graph_path=graph_path,
        )
        paths.current_path.write_text(result.merged_md)
        logger.info(
            "Merged current.md: %d confirmed, %d added, %d stale, %d orphaned",
            len(result.confirmed),
            len(result.added),
            len(result.stale),
            len(result.orphaned),
        )
        return paths.current_path, result
    except Exception as exc:
        logger.warning("Merge failed, falling back to clobber: %s", exc)
        paths.current_path.write_text(snapshot_md)
        return paths.current_path, None

