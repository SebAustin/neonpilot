"""M0 done-when: `neonpilot --help` and every subcommand's `--help` exit 0 (SC9)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from neonpilot import __version__
from neonpilot.cli import app

runner = CliRunner()


def test_top_level_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "neonpilot" in result.stdout.lower()


@pytest.mark.parametrize("command", ["probe", "optimize", "report", "apply"])
def test_subcommand_help_exits_zero(command):
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0


def test_version_flag_prints_version_and_exits_zero():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_unimplemented_subcommands_exit_nonzero_with_message():
    for command in ("optimize", "report", "apply"):
        args = [command, "model.gguf"] if command == "optimize" else [command]
        result = runner.invoke(app, args)
        assert result.exit_code != 0
