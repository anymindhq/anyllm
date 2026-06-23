"""Shared fixtures for anyllm tests."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def snapshot_v1() -> str:
    return (FIXTURES_DIR / "snapshot_v1.md").read_text()


@pytest.fixture
def snapshot_v2() -> str:
    return (FIXTURES_DIR / "snapshot_v2.md").read_text()


@pytest.fixture
def snapshot_v3() -> str:
    return (FIXTURES_DIR / "snapshot_v3.md").read_text()


@pytest.fixture
def graph_response_extracted() -> dict:
    import json
    return json.loads((FIXTURES_DIR / "graph_response_extracted.json").read_text())


@pytest.fixture
def graph_response_inferred() -> dict:
    import json
    return json.loads((FIXTURES_DIR / "graph_response_inferred.json").read_text())


@pytest.fixture
def graph_response_missing() -> dict:
    import json
    return json.loads((FIXTURES_DIR / "graph_response_missing.json").read_text())


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal anyllm project structure in a temp directory."""
    import json

    anyllm_dir = tmp_path / ".anyllm"
    anyllm_dir.mkdir()
    (anyllm_dir / "sessions").mkdir()
    (anyllm_dir / "index.json").write_text(json.dumps({"sessions": []}, indent=2))
    return tmp_path
