import re

from typer.testing import CliRunner

import replaykit
from replaypack.cli.app import app


def test_cli_version_option_reports_semver_like_value() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    reported = result.output.strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", reported) is not None
    assert reported == replaykit.__version__
