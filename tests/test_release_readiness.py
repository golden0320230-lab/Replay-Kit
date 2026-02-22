from pathlib import Path
import re

import replaykit


def test_release_artifacts_exist_and_version_is_semver_like() -> None:
    assert Path("CHANGELOG.md").exists()
    assert Path("docs/RELEASES.md").exists()
    assert re.fullmatch(r"\d+\.\d+\.\d+", replaykit.__version__) is not None


def test_release_docs_reference_tag_and_upgrade_policy() -> None:
    text = Path("docs/RELEASES.md").read_text(encoding="utf-8").lower()
    assert "semantic versioning" in text
    assert "git tag -a vx.y.z" in text
    assert "docs/public_api.md" in text
