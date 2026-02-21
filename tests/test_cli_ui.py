from typer.testing import CliRunner

from replaypack.cli.app import app


def test_cli_ui_check_starts_and_stops_server() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ui", "--check"])

    assert result.exit_code == 0
    assert "ui check ok" in result.stdout
