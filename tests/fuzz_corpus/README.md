# Fuzz Corpus

This directory stores deterministic fuzz seed inputs and repro payloads for ReplayPack stability tests.

## Layout

- `canonical/` seed values for canonicalization fuzz checks.
- `parser/` malformed artifact payloads for parser robustness checks.
- `diff/` run payload pairs for diff-engine robustness checks.
- `repro/` auto-retained reproductions for newly discovered fuzz failures.

## Repro retention

When a fuzz test detects an unexpected exception, the failing payload is written to `repro/` with a timestamped filename before the test fails.  
Keep that file in git when it represents a real regression case.
