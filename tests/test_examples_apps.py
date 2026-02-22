from pathlib import Path
import subprocess
import sys


def test_minimal_example_app_runs_without_external_network() -> None:
    app_path = Path("examples/apps/minimal_app.py")
    assert app_path.exists()

    result = subprocess.run(
        [sys.executable, str(app_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
