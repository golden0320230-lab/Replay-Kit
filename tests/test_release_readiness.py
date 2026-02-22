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


def test_readme_includes_ci_badge_and_stability_statement() -> None:
    text = Path("README.md").read_text(encoding="utf-8").lower()
    assert "actions/workflows/ci.yml/badge.svg" in text
    assert "compatibility & stability" in text
    assert "supported python versions" in text
    assert "platform guarantees" in text
    assert "semantic versioning policy" in text
    assert "backward compatibility guarantees" in text
