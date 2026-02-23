# Release Process

This document defines the release/tag workflow for ReplayKit.

## Version Source of Truth

- Runtime/library version is stored in `replaykit/__init__.py` as `__version__`.
- Release tags must match this value: `v<version>` (for example `v0.1.0`).

## Upgrade Policy

- Semantic versioning is used for public API behavior:
  - Patch: bug fixes and internal changes with no public API break.
  - Minor: additive public API changes.
  - Major: breaking public API changes.
- Public API compatibility contract is documented in `docs/PUBLIC_API.md`.
- Artifact schema migrations must remain documented in `docs/ARTIFACT_MIGRATION.md`.

## Cut a Release Tag

1. Ensure `main` is green in CI.
2. Update:
   - `replaykit/__init__.py` (`__version__`)
   - `CHANGELOG.md` (`[Unreleased]` -> new version/date section)
3. Commit and push:

```bash
git checkout main
git pull --rebase
git add replaykit/__init__.py CHANGELOG.md
git commit -m "chore(release): vX.Y.Z"
git push origin main
```

4. Create annotated tag and push:

```bash
git tag -a vX.Y.Z -m "ReplayKit vX.Y.Z"
git push origin vX.Y.Z
```

5. Create GitHub release notes from `CHANGELOG.md`:

```bash
gh release create vX.Y.Z --title "vX.Y.Z" --notes-file CHANGELOG.md
```

## Provider Capture + Target Recording Release Notes

Use the curated release notes file when shipping provider-capture and target-record
milestones:

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes-file docs/release-notes-provider-capture-target-recording.md
```

Recommended flow:

1. Update `docs/release-notes-provider-capture-target-recording.md`.
2. Cut and push tag (`vX.Y.Z`).
3. Publish release notes via `gh release create`.

## Verify Post-Release

```bash
python3 - <<'PY'
import replaykit
print(replaykit.__version__)
PY
```
