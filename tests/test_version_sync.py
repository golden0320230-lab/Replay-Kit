from __future__ import annotations

from pathlib import Path
import re

import replaykit


def test_runtime_version_matches_pyproject() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pyproject_path = repo_root / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")

    match = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"\s*$', content)
    assert match is not None, "Could not find [project].version in pyproject.toml"
    project_version = match.group(1)

    assert replaykit.__version__ == project_version
