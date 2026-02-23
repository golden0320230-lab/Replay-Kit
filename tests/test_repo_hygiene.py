from __future__ import annotations

from pathlib import Path

import pytest


REQUIRED_FILES = (
    "LICENSE",
    "SECURITY.md",
    "docs/PRODUCTION_READINESS.md",
)


@pytest.mark.parametrize("relative_path", REQUIRED_FILES)
def test_required_repo_hygiene_files_exist(relative_path: str) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert (repo_root / relative_path).is_file(), f"Missing required file: {relative_path}"
