"""Advanced CLI and module-entrypoint behavior tests."""

from __future__ import annotations

import subprocess
import sys

import pytest
from click.testing import CliRunner

from obfush import __version__
from obfush.cli import main
from obfush.config import ConfigError, validate_config


@pytest.mark.parametrize(
    ("option", "expected"),
    [
        ("--help", "Polymorphic Bash Obfuscation Engine"),
        ("--version", f"obfush, version {__version__}"),
        ("--help-advanced", "EVAL-MODE GUIDE"),
    ],
)
def test_eager_information_options_need_no_script_arguments(option, expected):
    result = CliRunner().invoke(main, [option])

    assert result.exit_code == 0, result.output
    assert expected in result.output


def test_python_module_entrypoint_exposes_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "obfush", "--version"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"obfush, version {__version__}" in result.stdout


def test_gui_mode_forwards_bind_options_without_running_engine(monkeypatch):
    launched = {}

    def launch(**options):
        launched.update(options)

    monkeypatch.setattr("obfush.gui.launch", launch)

    result = CliRunner().invoke(
        main,
        ["--gui", "--gui-host", "0.0.0.0", "--gui-port", "6123", "--no-browser"],
    )

    assert result.exit_code == 0, result.output
    assert launched == {"host": "0.0.0.0", "port": 6123, "open_browser": False}


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--setup", "input.sh", "output.sh"], "--setup cannot be combined"),
        (["--setup", "--gui"], "--setup cannot be combined"),
        (["--gui", "input.sh", "output.sh"], "--gui does not accept"),
    ],
)
def test_exclusive_execution_modes_reject_conflicts(arguments, message):
    result = CliRunner().invoke(main, arguments)

    assert result.exit_code == 2
    assert message in result.output


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ([], "Single-file mode requires"),
        (["missing.sh", "output.sh"], "Input script does not exist"),
        (["--benchmark", "-"], "must be a file"),
        (["-", "-", "--output-mode", "binary"], "requires a filesystem"),
        (["-", "-", "--intensity", "1.1"], "must be 0.0-1.0"),
    ],
)
def test_invalid_modes_and_paths_report_actionable_errors(arguments, message):
    result = CliRunner().invoke(main, arguments, input="echo hello\n")

    assert result.exit_code != 0
    assert message in result.output


def test_dry_run_reports_plan_and_does_not_create_output(tmp_path):
    destination = tmp_path / "would-be-output.sh"

    result = CliRunner().invoke(
        main,
        [
            "-",
            str(destination),
            "--no-config",
            "--seed",
            "42",
            "--layers",
            "id-mangle",
            "--min-layers",
            "1",
            "--dry-run",
        ],
        input="echo hello\n",
    )

    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert "id-mangle" in result.output
    assert not destination.exists()


def test_verbose_engine_failure_includes_context(monkeypatch, tmp_path):
    class FailingEngine:
        def __init__(self, config):
            assert config.verbose

        def run(self, source):
            raise RuntimeError("synthetic transform failure")

    monkeypatch.setattr("obfush.cli.PolymorphicEngine", FailingEngine)

    result = CliRunner().invoke(
        main,
        ["-", str(tmp_path / "output.sh"), "--no-config", "--verbose"],
        input="echo hello\n",
    )

    assert result.exit_code == 1
    assert "Engine error" in result.output
    assert "synthetic transform failure" in result.output
    assert "RuntimeError" in result.output


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"intensity": 0.0, "entropy_target": 8, "max_size_ratio": 1}, None),
        ({"intensity": True}, "intensity must be numeric"),
        ({"min_layers": True}, "min_layers must be an integer"),
        ({"eval_mode": "sometimes"}, "eval_mode must be"),
        ({"environment_key": ""}, "environment_key must be"),
        ({"force_layers": ["id-mangle", 3]}, "force_layers must be"),
        ({"test_input": 3}, "test_input must be"),
    ],
)
def test_configuration_validation_boundaries(config, expected):
    if expected is None:
        validated = validate_config(config)
        assert validated == {
            "intensity": 0.0,
            "entropy_target": 8.0,
            "max_size_ratio": 1.0,
        }
    else:
        with pytest.raises(ConfigError, match=expected):
            validate_config(config)
